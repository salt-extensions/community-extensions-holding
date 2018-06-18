# -*- coding: utf-8 -*-
'''
    :codeauthor: Pedro Algarvio (pedro@algarvio.me)

    tests.support.mock
    ~~~~~~~~~~~~~~~~~~

    Helper module that wraps `mock` and provides some fake objects in order to
    properly set the function/class decorators and yet skip the test case's
    execution.

    Note: mock >= 2.0.0 required since unittest.mock does not have
    MagicMock.assert_called in Python < 3.6.
'''
# pylint: disable=unused-import,function-redefined,blacklisted-module,blacklisted-external-module

from __future__ import absolute_import
import errno
import fnmatch
import sys

# Import salt libs
from salt.ext import six
import salt.utils.stringutils

try:
    from mock import (
        Mock,
        MagicMock,
        patch,
        sentinel,
        DEFAULT,
        # ANY and call will be imported further down
        create_autospec,
        FILTER_DIR,
        NonCallableMock,
        NonCallableMagicMock,
        PropertyMock,
        __version__
    )
    NO_MOCK = False
    NO_MOCK_REASON = ''
    mock_version = []
    for __part in __version__.split('.'):
        try:
            mock_version.append(int(__part))
        except ValueError:
            # Non-integer value (ex. '1a')
            mock_version.append(__part)
    mock_version = tuple(mock_version)
except ImportError as exc:
    NO_MOCK = True
    NO_MOCK_REASON = 'mock python module is unavailable'
    mock_version = (0, 0, 0)

    # Let's not fail on imports by providing fake objects and classes

    class MagicMock(object):

        # __name__ can't be assigned a unicode
        __name__ = str('{0}.fakemock').format(__name__)  # future lint: disable=blacklisted-function

        def __init__(self, *args, **kwargs):
            pass

        def dict(self, *args, **kwargs):
            return self

        def multiple(self, *args, **kwargs):
            return self

        def __call__(self, *args, **kwargs):
            return self

    Mock = MagicMock
    patch = MagicMock()
    sentinel = object()
    DEFAULT = object()
    create_autospec = MagicMock()
    FILTER_DIR = True
    NonCallableMock = MagicMock()
    NonCallableMagicMock = MagicMock()
    mock_open = object()
    PropertyMock = object()
    call = tuple
    ANY = object()


if NO_MOCK is False:
    try:
        from mock import call, ANY
    except ImportError:
        NO_MOCK = True
        NO_MOCK_REASON = 'you need to upgrade your mock version to >= 0.8.0'


class MockFH(object):
    def __init__(self, filename, read_data, *args, **kwargs):
        self.filename = filename
        self.call_args = (filename,) + args
        self.call_kwargs = kwargs
        self.empty_string = b'' if isinstance(read_data, six.binary_type) else ''
        self.read_data = self._iterate_read_data(read_data)
        self.read = Mock(side_effect=self._read)
        self.readlines = Mock(side_effect=self._readlines)
        self.readline = Mock(side_effect=self._readline)
        self.close = Mock()
        self.write = Mock()
        self.writelines = Mock()
        self.seek = Mock()
        self._loc = 0

    def _iterate_read_data(self, read_data):
        '''
        Helper for mock_open:
        Retrieve lines from read_data via a generator so that separate calls to
        readline, read, and readlines are properly interleaved
        '''
        # Newline will always be a bytestring on PY2 because mock_open will have
        # normalized it to one.
        newline = b'\n' if isinstance(read_data, six.binary_type) else '\n'

        read_data = [line + newline for line in read_data.split(newline)]

        if read_data[-1] == newline:
            # If the last line ended in a newline, the list comprehension will have an
            # extra entry that's just a newline. Remove this.
            read_data = read_data[:-1]
        else:
            # If there wasn't an extra newline by itself, then the file being
            # emulated doesn't have a newline to end the last line, so remove the
            # newline that we added in the list comprehension.
            read_data[-1] = read_data[-1][:-1]

        for line in read_data:
            yield line

    @property
    def write_calls(self):
        '''
        Return a list of all calls to the .write() mock
        '''
        return [x[1][0] for x in self.write.mock_calls]

    @property
    def writelines_calls(self):
        '''
        Return a list of all calls to the .writelines() mock
        '''
        return [x[1][0] for x in self.writelines.mock_calls]

    def tell(self):
        return self._loc

    def _read(self, size=0):
        if not isinstance(size, six.integer_types) or size < 0:
            raise TypeError('a positive integer is required')

        joined = self.empty_string.join(self.read_data)
        if not size:
            # read() called with no args, return everything
            self._loc += len(joined)
            return joined
        else:
            # read() called with an explicit size. Return a slice matching the
            # requested size, but before doing so, reset read_data to reflect
            # what we read.
            self.read_data = self._iterate_read_data(joined[size:])
            ret = joined[:size]
            self._loc += len(ret)
            return ret

    def _readlines(self, size=None):  # pylint: disable=unused-argument
        # TODO: Implement "size" argument
        ret = list(self.read_data)
        self._loc += sum(len(x) for x in ret)
        return ret

    def _readline(self, size=None):  # pylint: disable=unused-argument
        # TODO: Implement "size" argument
        try:
            ret = next(self.read_data)
            self._loc += len(ret)
            return ret
        except StopIteration:
            return self.empty_string

    def __iter__(self):
        while True:
            try:
                yield next(self.read_data)
            except StopIteration:
                break

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):  # pylint: disable=unused-argument
        pass


class MockOpen(object):
    r'''
    This class can be used to mock the use of ``open()``.

    ``read_data`` is a string representing the contents of the file to be read.
    By default, this is an empty string.

    Optionally, ``read_data`` can be a dictionary mapping ``fnmatch.fnmatch()``
    patterns to strings (or optionally, exceptions). This allows the mocked
    filehandle to serve content for more than one file path.

    .. code-block:: python

        data = {
            '/etc/foo.conf': textwrap.dedent("""\
                Foo
                Bar
                Baz
                """),
            '/etc/bar.conf': textwrap.dedent("""\
                A
                B
                C
                """),
        }
        with patch('salt.utils.files.fopen', mock_open(read_data=data):
            do stuff

    If the file path being opened does not match any of the glob expressions,
    an IOError will be raised to simulate the file not existing.

    Passing ``read_data`` as a string is equivalent to passing it with a glob
    expression of "*". That is to say, the below two invocations are
    equivalent:

    .. code-block:: python

        mock_open(read_data='foo\n')
        mock_open(read_data={'*': 'foo\n'})

    Instead of a string representing file contents, ``read_data`` can map to an
    exception, and that exception will be raised if a file matching that
    pattern is opened:

    .. code-block:: python

        data = {
            '/etc/*': IOError(errno.EACCES, 'Permission denied'),
            '*': 'Hello world!\n',
        }
        with patch('salt.utils.files.fopen', mock_open(read_data=data)):
            do stuff

    The above would raise an exception if any files within /etc are opened, but
    would produce a mocked filehandle if any other file is opened.

    To simulate file contents changing upon subsequent opens, the file contents
    can be a list of strings/exceptions. For example:

    .. code-block:: python

        data = {
            '/etc/foo.conf': [
                'before\n',
                'after\n',
            ],
            '/etc/bar.conf': [
                IOError(errno.ENOENT, 'No such file or directory', '/etc/bar.conf'),
                'Hey, the file exists now!',
            ],
        }
        with patch('salt.utils.files.fopen', mock_open(read_data=data):
            do stuff

    The first open of ``/etc/foo.conf`` would return "before\n" when read,
    while the second would return "after\n" when read. For ``/etc/bar.conf``,
    the first read would raise an exception, while the second would open
    successfully and read the specified string.

    Expressions will be attempted in dictionary iteration order (the exception
    being ``*`` which is tried last), so if a file path matches more than one
    fnmatch expression then the first match "wins". If your use case calls for
    overlapping expressions, then an OrderedDict can be used to ensure that the
    desired matching behavior occurs:

    .. code-block:: python

        data = OrderedDict()
        data['/etc/foo.conf'] = 'Permission granted!'
        data['/etc/*'] = IOError(errno.EACCES, 'Permission denied')
        data['*'] = '*': 'Hello world!\n'
        with patch('salt.utils.files.fopen', mock_open(read_data=data):
            do stuff

    The following attributes are tracked for the life of a mock object:

    * call_count - Tracks how many fopen calls were attempted
    * filehandles - This is a dictionary mapping filenames to lists of MockFH
      objects, representing the individual times that a given file was opened.
    '''
    def __init__(self, read_data=''):
        # Normalize read_data, Python 2 filehandles should never produce unicode
        # types on read.
        if not isinstance(read_data, dict):
            read_data = {'*': read_data}

        if six.PY2:
            # .__class__() used here to preserve the dict class in the event that
            # an OrderedDict was used.
            new_read_data = read_data.__class__()
            for key, val in six.iteritems(read_data):
                try:
                    val = salt.utils.data.decode(val, to_str=True)
                except TypeError:
                    if not isinstance(val, BaseException):
                        raise
                new_read_data[key] = val

            read_data = new_read_data
            del new_read_data

        self.read_data = read_data
        self.filehandles = {}
        self.call_count = 0

    def __call__(self, name, *args, **kwargs):
        '''
        Match the file being opened to the patterns in the read_data and spawn
        a mocked filehandle with the corresponding file contents.
        '''
        self.call_count += 1
        for pat in self.read_data:
            if pat == '*':
                continue
            if fnmatch.fnmatch(name, pat):
                matched_pattern = pat
                break
        else:
            # No non-glob match in read_data, fall back to '*'
            matched_pattern = '*'
        try:
            matched_contents = self.read_data[matched_pattern]
            try:
                # Assuming that the value for the matching expression is a
                # list, pop the first element off of it.
                file_contents = matched_contents.pop(0)
            except AttributeError:
                # The value for the matching expression is a string (or exception)
                file_contents = matched_contents
            except IndexError:
                # We've run out of file contents, abort!
                raise RuntimeError(
                    'File matching expression \'{0}\' opened more times than '
                    'expected'.format(matched_pattern)
                )

            try:
                # Raise the exception if the matched file contents are an
                # instance of an exception class.
                raise file_contents
            except TypeError:
                # Contents were not an exception, so proceed with creating the
                # mocked filehandle.
                pass

            ret = MockFH(name, file_contents, *args, **kwargs)
            self.filehandles.setdefault(name, []).append(ret)
            return ret
        except KeyError:
            # No matching glob in read_data, treat this as a file that does
            # not exist and raise the appropriate exception.
            raise IOError(errno.ENOENT, 'No such file or directory', name)

    def write_calls(self, path=None):
        '''
        Returns the contents passed to all .write() calls. Use `path` to narrow
        the results to files matching a given pattern.
        '''
        ret = []
        for filename, handles in six.iteritems(self.filehandles):
            if path is None or fnmatch.fnmatch(filename, path):
                for fh_ in handles:
                    ret.extend(fh_.write_calls)
        return ret

    def writelines_calls(self, path=None):
        '''
        Returns the contents passed to all .writelines() calls. Use `path` to
        narrow the results to files matching a given pattern.
        '''
        ret = []
        for filename, handles in six.iteritems(self.filehandles):
            if path is None or fnmatch.fnmatch(filename, path):
                for fh_ in handles:
                    ret.extend(fh_.writelines_calls)
        return ret


# reimplement mock_open to support multiple filehandles
mock_open = MockOpen
