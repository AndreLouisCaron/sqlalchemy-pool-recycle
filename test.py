# -*- coding: utf-8 -*-


import os.path
import pymysql
import pymysql.cursors
import pymysql.err
import pytest
import sqlalchemy
import sqlalchemy.event
import sqlalchemy.exc
import time

from timeit import default_timer as clock


@pytest.fixture(scope='session')
def docker_compose_file(pytestconfig):
    """Point pytest-docker to our docker-compose.yml file."""
    return os.path.join(str(pytestconfig.rootdir), 'docker-compose.yml')


@pytest.fixture(scope='session')
def mysql(docker_ip, docker_services):
    """Wait for MySQL to become responsive and return connection info."""

    port = docker_services.port_for('mysql', 3306)
    username = 'root'
    password = '1234'

    def is_responsive():
        """Check if MySQL is responsive."""
        try:
            connection = pymysql.connect(
                host=docker_ip,
                port=port,
                user=username,
                password=password,
                charset='utf8',
                cursorclass=pymysql.cursors.DictCursor,
            )
        except pymysql.err.OperationalError as error:
            if error.args[0] != 2003:
                raise
            return False
        else:
            connection.close()
            return True

    docker_services.wait_until_responsive(
        timeout=30.0, pause=0.1,
        check=is_responsive,
    )

    # Return all info for connecting.
    return (docker_ip, port, username, password)


@pytest.mark.parametrize('total_time,sleep_time,pool_recycle', [
    (15.0, 1.0, -1),  # none
    (15.0, 1.0,  5),  # expire after 5 seconds
])
def test_pool_recycle(mysql, total_time, sleep_time, pool_recycle):
    """Check pool recycle behavior."""

    # Show output on fresh line.
    print()

    # Prepare the engine.
    engine = sqlalchemy.create_engine(
        'mysql+pymysql://%s:%s@%s:%s' % (
            mysql[2],       # username
            mysql[3],       # password
            mysql[0],       # host
            str(mysql[1]),  # port
        ),
        pool_recycle=pool_recycle,
    )

    # Print something each time we open a new connection.
    @sqlalchemy.event.listens_for(engine, 'connect')
    def connect(*args, **kwds):
        print('  connect')

    # Print something each time we close a connection.
    @sqlalchemy.event.listens_for(engine, 'close')
    def close(*args, **kwds):
        print('  close')

    # Poke MySQL a few times to see what happens.
    ref = clock()
    now = ref
    while (now - ref) < total_time:
        r = engine.execute('SELECT 1').fetchall()
        assert len(r) == 1
        assert r[0] == (1,)
        print('.')
        time.sleep(sleep_time)
        now = clock()


@pytest.mark.parametrize('total_time,sleep_time,idle_time', [
    (15.0, 1.0, None),  # never expire
    (15.0, 1.0,  3.0),  # always re-use before expiration
    (15.0, 5.0,  3.0),  # expire each time due to infrequent access
])
def test_pool_idle_time(mysql, total_time, sleep_time, idle_time):
    """Showcase how to close connections that are idle for too long."""

    # Show output on fresh line.
    print()

    # Prepare the engine.
    engine = sqlalchemy.create_engine(
        'mysql+pymysql://%s:%s@%s:%s' % (
            mysql[2],       # username
            mysql[3],       # password
            mysql[0],       # host
            str(mysql[1]),  # port
        ),
        pool_recycle=-1,
    )

    # Translate pool_recycle to idle time.
    if idle_time is None:
        idle_time = float('+inf')

    # Impose a limit on idle time.
    @sqlalchemy.event.listens_for(engine, 'checkout')
    def checkout(dbapi_connection, connection_record, connection_proxy):
        now = time.time()
        checkout_time = connection_record.info.get('checkout_time')
        if checkout_time and now - checkout_time > idle_time:
            raise sqlalchemy.exc.DisconnectionError(
                "recycling connection idle past %s seconds" % idle_time
            )
        connection_record.info['checkout_time'] = now

    # Print something each time we open a new connection.
    @sqlalchemy.event.listens_for(engine, 'connect')
    def connect(*args, **kwds):
        print('  connect')

    # Print something each time we close a connection.
    @sqlalchemy.event.listens_for(engine, 'close')
    def close(*args, **kwds):
        print('  close')

    # Poke MySQL a few times to see what happens.
    ref = clock()
    now = ref
    while (now - ref) < total_time:
        r = engine.execute('SELECT 1').fetchall()
        assert len(r) == 1
        assert r[0] == (1,)
        print('.')
        time.sleep(sleep_time)
        now = clock()
