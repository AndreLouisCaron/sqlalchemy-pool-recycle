# -*- coding: utf-8 -*-


import os.path
import pymysql
import pymysql.cursors
import pymysql.err
import pytest
import sqlalchemy
import sqlalchemy.event
import time

from datetime import timedelta


@pytest.fixture(scope='session')
def docker_compose_file(pytestconfig):
    """Point pytest-docker to our docker-compose.yml file."""
    return os.path.join(str(pytestconfig.rootdir), 'docker-compose.yml')


@pytest.fixture(scope='session')
def mysql(docker_ip, docker_services):
    """Create an engine that talks to our Docker container."""

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


@pytest.mark.parametrize('pool_recycle', [
    -1,  # none
    5,   # expire after 5 seconds
])
def test_pool_recycle(mysql, pool_recycle):
    """Check pool recycle behavior."""

    # Show output on fresh line.
    print()

    if isinstance(pool_recycle, timedelta):
        pool_recycle = pool_recycle.total_seconds()

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
    #
    # Because ``pool_recycle`` checks the connection *age* rather than the
    # connection idle time, we'll see repeated reconnections throughout this
    # loop.
    for i in range(15):
        r = engine.execute('SELECT 1').fetchall()
        assert len(r) == 1
        assert r[0] == (1,)
        print('.')
        time.sleep(1.0)
