from __future__ import absolute_import

import os

from . import fn
from .compat import json_loads
from .fn import curry, flat_map, maybe, merge
from .tar import mkcontext


# (container->(str -> None))
#   -> (container -> stream)
#   -> [targets]
#   -> [(container, docker_image_id)]
def do_build(client, git_rev, targets):
    """
    Generic function for building multiple containers while
    notifying a callback function with output produced.

    Given a list of targets it builds the target with the given
    build_func while streaming the output through the given
    show_func.

    Returns an iterator of (container, docker_image_id) pairs as
    the final output.

    Building a container can take sometime so  the results are returned as
    an iterator in case the caller wants to use restults in between builds.

    The consequences of this is you must either call it as part of a for loop
    or pass it to a function like list() which can consume an iterator.

    """

    return flat_map(build(client, git_rev), targets)


@curry
def build(client, git_rev, container):
    """
    builds the given container tagged with <git_rev> and ensures that
    it depends on it's parent if it's part of this build group (shares
    the same namespace)
    """

    merge_config = {
        'event': "build_msg",
        'container': container,
        'rev': git_rev
    }

    # docker-py has an issue where it doesn't handle chunked responses from
    # Docker correctly, and so the build API yields *chunks*, rather than the
    # valid JSON objects that it is documented as yielding.
    # We therefore maintain a buffer and read our own valid JSON out of that.
    # This can probably be replaced this issue is fixed - ideally we'd use the
    # 'decode' option on client.build to receive already parsed JSON objects.
    #   https://github.com/docker/docker-py/issues/1059
    buffer = b''

    def process_event_(buffer, data):
        buffer += data
        for line in buffer.split(b'\r\n'):
            if not line:
                continue

            try:
                event = json_loads(line)
            except ValueError:
                continue

            yield merge(merge_config)(event)

    build_evts = client.build(
        fileobj=mkcontext(git_rev, container.path),
        rm=True,
        custom_context=True,
        stream=True,
        tag='{0}:{1}'.format(container.name, git_rev),
        dockerfile=os.path.basename(container.path),
    )

    return (
        evt
        for raw_evt in build_evts
        for evt in process_event_(buffer, raw_evt)
    )


@fn.composed(maybe(fn._0), fn.search(r'^Successfully built ([a-f0-9]+)\s*$'))
def success(line):
    """
    >>> success('Blah')
    >>> success('Successfully built 1234\\n')
    '1234'
    """


@fn.composed(fn.first, fn.filter(None), fn.map(success))
def success_from_stream(stream):
    """

    >>> stream = iter(('Blah', 'Successfully built 1234\\n'))
    >>> success_from_stream(stream)
    '1234'
    """
