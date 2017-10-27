.. -*- coding: utf-8 -*-


===============================================================
  sqlalchemy-pool-recycle: Grokking SQLAlchemy's pool recycle
===============================================================

Executable demonstration of SQLAclhemy's pool recycle behavior against MySQL.

When running this demo, you will see the behavior of SQLAlchmy's pool recycle
behavior.  The expeceted output is that you see (very) aggressive reconnections
to MySQL.  This demo accelerates the behavior to show it in a reasonable amount
of time, but it clearly shows that the pool recycle setting does not measure
connection idle time as one would reasonably expect.

Behavior analysis
-----------------

SQLAlchemy's documentation describes the rationale behind the ``pool_recycle``
setting:

   This parameter prevents the pool from using a particular connection that has
   passed a certain age, and is appropriate for database backends such as MySQL
   that automatically close connections that have been stale after a particular
   period of time

   -- `Setting Pool Recycle`_ (SQLAlchemy documentation)

.. _`Setting Pool Recycle`: http://docs.sqlalchemy.org/en/latest/core/pooling.html#setting-pool-recycle

The rationale behind this setting suggests its rationale is to pre-emptivly
close the connection before MySQL does.  This intent clearly aims a protecting
your applicaiton from MySQL's ``wait_timeout`` system variable, which has the
following description:

   The number of seconds the server waits for activity on a noninteractive
   connection before closing it.

   -- `Server System Variables / wait_timeout`_ (MySQL documentation)

.. _`Server System Variables / wait_timeout`: https://dev.mysql.com/doc/refman/5.7/en/server-system-variables.html#sysvar_wait_timeout

There is an important difference in behaivor here:

#. MySQL closes connections based on the time elapsed since the connection was
   last used; whereas
#. SQLAlchemy closes the connection based on the time since it was first opened
   (rather than when it was last returned to the pool).

Impact on server applications
-----------------------------

In server applications that require low latency to MySQL, proper connection
pooling is vital to performance.  The ideal scenario is that the server
application never needs to reconnect to MySQL during busy periods.  However,
when you set the ``pool_recycle`` setting, SQLAlchemy will periodically close
each connection in the pool.

When you have an application that scales its threads/processes based on
incoming traffic, it's normal to see a burst of connections to MySQL opened in
a very short period.  When the ``pool_recycle`` setting is set, this causes a
hammer effect with a periodic reconnection of that initial burst of
connections.

I have not observed this behavior to cause any notable impact on MySQL
performance, but I have measured periodic increases in latency due to these
unnecessary reconnections.

This hammer will smooth out over a long time due to natural randomization of
access patterns, but it's still annoying that the performance is flaky like
this because it creates noise in performance analysis and distracts from
flakyness in application code's performance (which should be optimized).

The connection pool we should have
----------------------------------

The problem described in server applications is a real one.  It still affects
your application during quiet periods where connections are infrequently used.
There is a real risk that you send your updates over a stale connection and
having to implement complex retry logic for updates that aren't idempotent.

Of course, this can always happen in case of a real network connection loss and
you need to handle it, but it's better for performance not to have to trigger
this code path as often.

The ideal scenario is to track time since last use of the connection on both
ends with a timeout that is (slightly) shorter on the client than on server.

Recommendation
--------------

I contacted the SQLAlchemy developers on the support mailing list and they had
some really interesting insight on how to handle this issue.

Based on this discussion, I recommend implementing your own disconnections
based on idle time.  There is a really simple way to add it:

.. code-block:: python

       import sqlalchemy
       import sqlalchemy.event
       import sqlalchemy.exc

       engine = sqlalchemy.create_engine(...)

       idle_time = 30.0  # seconds.

       @sqlalchemy.event.listens_for(engine, 'checkout')
       def checkout(dbapi_connection, connection_record, connection_proxy):
           now = time.time()
           checkout_time = connection_record.info.get('checkout_time')
           if checkout_time and now - checkout_time > idle_time:
               raise sqlalchemy.exc.DisconnectionError(
                   "recycling connection idle past %s seconds" % idle_time
               )
           connection_record.info['checkout_time'] = now

You may still want to keep the ``pool_recycle`` setting as a crude form of
garbage collection on both the client & server.  Ideally, this should be set to
a really high time (e.g. a few hours) if you want to maximize the effectiveness
of the connection pool.


Prerequisites
=============

Running this demo requires:

#. Docker_ (Docker-Machine_ works)
#. Python_ 3.5 or later
#. Tox_

.. _Docker: https://www.docker.com/
.. _Docker-Machine: https://docs.docker.com/machine/
.. _Python: https://www.python.org/
.. _Tox: https://tox.readthedocs.io/


Running the demo
================

Test your Docker daemon::

   docker ps

Run the demo through Tox::

   tox

Example output for the pool recycle setting::

   test.py::test_pool_recycle[-1]
     connect
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   PASSED
   test.py::test_pool_recycle[5]
     connect
   .
   .
   .
   .
   .
     close
     connect
   .
   .
   .
   .
   .
     close
     connect
   .
   .
   .
   .
   .
   PASSED

You can see that the second example (with 5 second pool recycle) periodically
reconnects.  If the pool worked as recommended, we would not see any
reconnections during the test.

Example output for the custom idle time setting::

   test.py::test_pool_idle_time[15.0-1.0-3.0]
     connect
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   .
   PASSED
   test.py::test_pool_idle_time[15.0-5.0-3.0]
     connect
   .
     close
     connect
   .
     close
     connect
   .
   PASSED


Updating dependencies
=====================

If you want to test against different versions of Python libraries, you will
need to edit ``requirements.in`` and then recompile dependencies::

  tox -e deps
  tox -r --notest

Then, you can re-run the demo as usual.
