# -*- coding: utf-8 -*-
#
# python-json-patch - An implementation of the JSON Patch format
# https://github.com/stefankoegl/python-json-patch
#
# Copyright (c) 2011 Stefan Kögl <stefan@skoegl.net>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. The name of the author may not be used to endorse or promote products
#    derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
# NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
# THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

""" Apply JSON-Patches (RFC 6902) """

from __future__ import unicode_literals

import collections
import copy
import functools
import json
import sys

try:
    from collections.abc import Sequence
except ImportError:  # Python 3
    from collections import Sequence

try:
    from types import MappingProxyType
except ImportError:
    # Python < 3.3
    MappingProxyType = dict

from jsonpointer import JsonPointer, JsonPointerException


_ST_ADD = 0
_ST_REMOVE = 1


try:
    from collections.abc import MutableMapping, MutableSequence

except ImportError:
    from collections import MutableMapping, MutableSequence
    str = unicode

# Will be parsed by setup.py to determine package metadata
__author__ = 'Stefan Kögl <stefan@skoegl.net>'
__version__ = '1.33'
__website__ = 'https://github.com/stefankoegl/python-json-patch'
__license__ = 'Modified BSD License'


# pylint: disable=E0611,W0404
if sys.version_info >= (3, 0):
    basestring = (bytes, str)  # pylint: disable=C0103,W0622


class JsonPatchException(Exception):
    """Base Json Patch exception"""


class InvalidJsonPatch(JsonPatchException):
    """ Raised if an invalid JSON Patch is created """


class JsonPatchConflict(JsonPatchException):
    """Raised if patch could not be applied due to conflict situation such as:
    - attempt to add object key when it already exists;
    - attempt to operate with nonexistence object key;
    - attempt to insert value to array at position beyond its size;
    - etc.
    """


class JsonPatchTestFailed(JsonPatchException, AssertionError):
    """ A Test operation failed """


def multidict(ordered_pairs):
    """Convert duplicate keys values to lists."""
    # read all values into lists
    mdict = collections.defaultdict(list)
    for key, value in ordered_pairs:
        mdict[key].append(value)

    return dict(
        # unpack lists that have only 1 item
        (key, values[0] if len(values) == 1 else values)
        for key, values in mdict.items()
    )


# The "object_pairs_hook" parameter is used to handle duplicate keys when
# loading a JSON object.
_jsonloads = functools.partial(json.loads, object_pairs_hook=multidict)


def apply_patch(doc, patch, in_place=False, pointer_cls=JsonPointer):
    """Apply list of patches to specified json document.

    :param doc: Document object.
    :type doc: dict

    :param patch: JSON patch as list of dicts or raw JSON-encoded string.
    :type patch: list or str

    :param in_place: While :const:`True` patch will modify target document.
                     By default patch will be applied to document copy.
    :type in_place: bool

    :param pointer_cls: JSON pointer class to use.
    :type pointer_cls: Type[JsonPointer]

    :return: Patched document object.
    :rtype: dict

    >>> doc = {'foo': 'bar'}
    >>> patch = [{'op': 'add', 'path': '/baz', 'value': 'qux'}]
    >>> other = apply_patch(doc, patch)
    >>> doc is not other
    True
    >>> other == {'foo': 'bar', 'baz': 'qux'}
    True
    >>> patch = [{'op': 'add', 'path': '/baz', 'value': 'qux'}]
    >>> apply_patch(doc, patch, in_place=True) == {'foo': 'bar', 'baz': 'qux'}
    True
    >>> doc == other
    True
    """

    if isinstance(patch, basestring):
        patch = JsonPatch.from_string(patch, pointer_cls=pointer_cls)
    else:
        patch = JsonPatch(patch, pointer_cls=pointer_cls)
    return patch.apply(doc, in_place)


def make_patch(src, dst, pointer_cls=JsonPointer):
    """Generates patch by comparing two document objects. Actually is
    a proxy to :meth:`JsonPatch.from_diff` method.

    :param src: Data source document object.
    :type src: dict

    :param dst: Data source document object.
    :type dst: dict

    :param pointer_cls: JSON pointer class to use.
    :type pointer_cls: Type[JsonPointer]

    >>> src = {'foo': 'bar', 'numbers': [1, 3, 4, 8]}
    >>> dst = {'baz': 'qux', 'numbers': [1, 4, 7]}
    >>> patch = make_patch(src, dst)
    >>> new = patch.apply(src)
    >>> new == dst
    True
    """

    return JsonPatch.from_diff(src, dst, pointer_cls=pointer_cls)


def rebase(base, applied, pending, pointer_cls=JsonPointer):
    """Rebase *pending* onto an *applied* patch made from *base*.

    The result is a JSON-serializable mapping with two members:

    ``patch``
        Operations from *pending* with object keys and array indices
        translated to the document produced by applying *applied*.

    ``conflicts``
        Operations that do not have a unique safe rebase. Conflicting
        operations are omitted from ``patch``.

    The three input arguments are never modified.
    """

    applied_patch = _coerce_patch(applied, pointer_cls)
    pending_patch = _coerce_patch(pending, pointer_cls)

    rebaser = _Rebaser(copy.deepcopy(base), pointer_cls)

    for index, operation in enumerate(applied_patch):
        rebaser.apply_applied(operation, index)

    for index, operation in enumerate(pending_patch):
        rebaser.apply_pending(operation, index)

    return {
        'patch': rebaser.pending_patch,
        'conflicts': rebaser.conflicts,
    }


def _coerce_patch(patch, pointer_cls):
    if isinstance(patch, basestring):
        return JsonPatch.from_string(patch, pointer_cls=pointer_cls).patch
    if isinstance(patch, JsonPatch):
        return patch.patch
    JsonPatch(patch, pointer_cls=pointer_cls)
    return patch


class PatchOperation(object):
    """A single operation inside a JSON Patch."""

    def __init__(self, operation, pointer_cls=JsonPointer):
        self.pointer_cls = pointer_cls

        if not operation.__contains__('path'):
            raise InvalidJsonPatch("Operation must have a 'path' member")

        if isinstance(operation['path'], self.pointer_cls):
            self.location = operation['path'].path
            self.pointer = operation['path']
        else:
            self.location = operation['path']
            try:
                self.pointer = self.pointer_cls(self.location)
            except TypeError as ex:
                raise InvalidJsonPatch("Invalid 'path'")

        self.operation = operation

    def apply(self, obj):
        """Abstract method that applies a patch operation to the specified object."""
        raise NotImplementedError('should implement the patch operation.')

    def __hash__(self):
        return hash(frozenset(self.operation.items()))

    def __eq__(self, other):
        if not isinstance(other, PatchOperation):
            return False
        return self.operation == other.operation

    def __ne__(self, other):
        return not(self == other)

    @property
    def path(self):
        return '/'.join(self.pointer.parts[:-1])

    @property
    def key(self):
        try:
            return int(self.pointer.parts[-1])
        except ValueError:
            return self.pointer.parts[-1]

    @key.setter
    def key(self, value):
        self.pointer.parts[-1] = str(value)
        self.location = self.pointer.path
        self.operation['path'] = self.location


class RemoveOperation(PatchOperation):
    """Removes an object property or an array element."""

    def apply(self, obj):
        subobj, part = self.pointer.to_last(obj)

        if isinstance(subobj, Sequence) and not isinstance(part, int):
            raise JsonPointerException("invalid array index '{0}'".format(part))

        try:
            del subobj[part]
        except (KeyError, IndexError) as ex:
            msg = "can't remove a non-existent object '{0}'".format(part)
            raise JsonPatchConflict(msg)

        return obj

    def _on_undo_remove(self, path, key):
        if self.path == path:
            if self.key >= key:
                self.key += 1
            else:
                key -= 1
        return key

    def _on_undo_add(self, path, key):
        if self.path == path:
            if self.key > key:
                self.key -= 1
            else:
                key -= 1
        return key


class AddOperation(PatchOperation):
    """Adds an object property or an array element."""

    def apply(self, obj):
        try:
            value = self.operation["value"]
        except KeyError as ex:
            raise InvalidJsonPatch(
                "The operation does not contain a 'value' member")

        subobj, part = self.pointer.to_last(obj)

        if isinstance(subobj, MutableSequence):
            if part == '-':
                subobj.append(value)  # pylint: disable=E1103

            elif part > len(subobj) or part < 0:
                raise JsonPatchConflict("can't insert outside of list")

            else:
                subobj.insert(part, value)  # pylint: disable=E1103

        elif isinstance(subobj, MutableMapping):
            if part is None:
                obj = value  # we're replacing the root
            else:
                subobj[part] = value

        else:
            if part is None:
                raise TypeError("invalid document type {0}".format(type(subobj)))
            else:
                raise JsonPatchConflict("unable to fully resolve json pointer {0}, part {1}".format(self.location, part))
        return obj

    def _on_undo_remove(self, path, key):
        if self.path == path:
            if self.key > key:
                self.key += 1
            else:
                key += 1
        return key

    def _on_undo_add(self, path, key):
        if self.path == path:
            if self.key > key:
                self.key -= 1
            else:
                key += 1
        return key


class ReplaceOperation(PatchOperation):
    """Replaces an object property or an array element by a new value."""

    def apply(self, obj):
        try:
            value = self.operation["value"]
        except KeyError as ex:
            raise InvalidJsonPatch(
                "The operation does not contain a 'value' member")

        subobj, part = self.pointer.to_last(obj)

        if part is None:
            return value

        if part == "-":
            raise InvalidJsonPatch("'path' with '-' can't be applied to 'replace' operation")

        if isinstance(subobj, MutableSequence):
            if part >= len(subobj) or part < 0:
                raise JsonPatchConflict("can't replace outside of list")

        elif isinstance(subobj, MutableMapping):
            if part not in subobj:
                msg = "can't replace a non-existent object '{0}'".format(part)
                raise JsonPatchConflict(msg)
        else:
            if part is None:
                raise TypeError("invalid document type {0}".format(type(subobj)))
            else:
                raise JsonPatchConflict("unable to fully resolve json pointer {0}, part {1}".format(self.location, part))

        subobj[part] = value
        return obj

    def _on_undo_remove(self, path, key):
        return key

    def _on_undo_add(self, path, key):
        return key


class MoveOperation(PatchOperation):
    """Moves an object property or an array element to a new location."""

    def apply(self, obj):
        try:
            if isinstance(self.operation['from'], self.pointer_cls):
                from_ptr = self.operation['from']
            else:
                from_ptr = self.pointer_cls(self.operation['from'])
        except KeyError as ex:
            raise InvalidJsonPatch(
                "The operation does not contain a 'from' member")

        subobj, part = from_ptr.to_last(obj)
        try:
            value = subobj[part]
        except (KeyError, IndexError) as ex:
            raise JsonPatchConflict(str(ex))

        # If source and target are equal, this is a no-op
        if self.pointer == from_ptr:
            return obj

        if isinstance(subobj, MutableMapping) and \
                self.pointer.contains(from_ptr):
            raise JsonPatchConflict('Cannot move values into their own children')

        obj = RemoveOperation({
            'op': 'remove',
            'path': self.operation['from']
        }, pointer_cls=self.pointer_cls).apply(obj)

        obj = AddOperation({
            'op': 'add',
            'path': self.location,
            'value': value
        }, pointer_cls=self.pointer_cls).apply(obj)

        return obj

    @property
    def from_path(self):
        from_ptr = self.pointer_cls(self.operation['from'])
        return '/'.join(from_ptr.parts[:-1])

    @property
    def from_key(self):
        from_ptr = self.pointer_cls(self.operation['from'])
        try:
            return int(from_ptr.parts[-1])
        except TypeError:
            return from_ptr.parts[-1]

    @from_key.setter
    def from_key(self, value):
        from_ptr = self.pointer_cls(self.operation['from'])
        from_ptr.parts[-1] = str(value)
        self.operation['from'] = from_ptr.path

    def _on_undo_remove(self, path, key):
        if self.from_path == path:
            if self.from_key >= key:
                self.from_key += 1
            else:
                key -= 1
        if self.path == path:
            if self.key > key:
                self.key += 1
            else:
                key += 1
        return key

    def _on_undo_add(self, path, key):
        if self.from_path == path:
            if self.from_key > key:
                self.from_key -= 1
            else:
                key -= 1
        if self.path == path:
            if self.key > key:
                self.key -= 1
            else:
                key += 1
        return key


class TestOperation(PatchOperation):
    """Test value by specified location."""

    def apply(self, obj):
        try:
            subobj, part = self.pointer.to_last(obj)
            if part is None:
                val = subobj
            else:
                val = self.pointer.walk(subobj, part)
        except JsonPointerException as ex:
            raise JsonPatchTestFailed(str(ex))

        try:
            value = self.operation['value']
        except KeyError as ex:
            raise InvalidJsonPatch(
                "The operation does not contain a 'value' member")

        if val != value:
            msg = '{0} ({1}) is not equal to tested value {2} ({3})'
            raise JsonPatchTestFailed(msg.format(val, type(val),
                                                 value, type(value)))

        return obj


class CopyOperation(PatchOperation):
    """ Copies an object property or an array element to a new location """

    def apply(self, obj):
        try:
            from_ptr = self.pointer_cls(self.operation['from'])
        except KeyError as ex:
            raise InvalidJsonPatch(
                "The operation does not contain a 'from' member")

        subobj, part = from_ptr.to_last(obj)
        try:
            value = copy.deepcopy(subobj[part])
        except (KeyError, IndexError) as ex:
            raise JsonPatchConflict(str(ex))

        obj = AddOperation({
            'op': 'add',
            'path': self.location,
            'value': value
        }, pointer_cls=self.pointer_cls).apply(obj)

        return obj


class JsonPatch(object):
    json_dumper = staticmethod(json.dumps)
    json_loader = staticmethod(_jsonloads)

    operations = MappingProxyType({
        'remove': RemoveOperation,
        'add': AddOperation,
        'replace': ReplaceOperation,
        'move': MoveOperation,
        'test': TestOperation,
        'copy': CopyOperation,
    })

    """A JSON Patch is a list of Patch Operations.

    >>> patch = JsonPatch([
    ...     {'op': 'add', 'path': '/foo', 'value': 'bar'},
    ...     {'op': 'add', 'path': '/baz', 'value': [1, 2, 3]},
    ...     {'op': 'remove', 'path': '/baz/1'},
    ...     {'op': 'test', 'path': '/baz', 'value': [1, 3]},
    ...     {'op': 'replace', 'path': '/baz/0', 'value': 42},
    ...     {'op': 'remove', 'path': '/baz/1'},
    ... ])
    >>> doc = {}
    >>> result = patch.apply(doc)
    >>> expected = {'foo': 'bar', 'baz': [42]}
    >>> result == expected
    True

    JsonPatch object is iterable, so you can easily access each patch
    statement in a loop:

    >>> lpatch = list(patch)
    >>> expected = {'op': 'add', 'path': '/foo', 'value': 'bar'}
    >>> lpatch[0] == expected
    True
    >>> lpatch == patch.patch
    True

    Also JsonPatch could be converted directly to :class:`bool` if it contains
    any operation statements:

    >>> bool(patch)
    True
    >>> bool(JsonPatch([]))
    False

    This behavior is very handy with :func:`make_patch` to write more readable
    code:

    >>> old = {'foo': 'bar', 'numbers': [1, 3, 4, 8]}
    >>> new = {'baz': 'qux', 'numbers': [1, 4, 7]}
    >>> patch = make_patch(old, new)
    >>> if patch:
    ...     # document have changed, do something useful
    ...     patch.apply(old)    #doctest: +ELLIPSIS
    {...}
    """
    def __init__(self, patch, pointer_cls=JsonPointer):
        self.patch = patch
        self.pointer_cls = pointer_cls

        # Verify that the structure of the patch document
        # is correct by retrieving each patch element.
        # Much of the validation is done in the initializer
        # though some is delayed until the patch is applied.
        for op in self.patch:
            # We're only checking for basestring in the following check
            # for two reasons:
            #
            # - It should come from JSON, which only allows strings as
            #   dictionary keys, so having a string here unambiguously means
            #   someone used: {"op": ..., ...} instead of [{"op": ..., ...}].
            #
            # - There's no possible false positive: if someone give a sequence
            #   of mappings, this won't raise.
            if isinstance(op, basestring):
                raise InvalidJsonPatch("Document is expected to be sequence of "
                                       "operations, got a sequence of strings.")

            self._get_operation(op)

    def __str__(self):
        """str(self) -> self.to_string()"""
        return self.to_string()

    def __bool__(self):
        return bool(self.patch)

    __nonzero__ = __bool__

    def __iter__(self):
        return iter(self.patch)

    def __hash__(self):
        return hash(tuple(self._ops))

    def __eq__(self, other):
        if not isinstance(other, JsonPatch):
            return False
        return self._ops == other._ops

    def __ne__(self, other):
        return not(self == other)

    @classmethod
    def from_string(cls, patch_str, loads=None, pointer_cls=JsonPointer):
        """Creates JsonPatch instance from string source.

        :param patch_str: JSON patch as raw string.
        :type patch_str: str

        :param loads: A function of one argument that loads a serialized
                      JSON string.
        :type loads: function

        :param pointer_cls: JSON pointer class to use.
        :type pointer_cls: Type[JsonPointer]

        :return: :class:`JsonPatch` instance.
        """
        json_loader = loads or cls.json_loader
        patch = json_loader(patch_str)
        return cls(patch, pointer_cls=pointer_cls)

    @classmethod
    def from_diff(
            cls, src, dst, optimization=True, dumps=None,
            pointer_cls=JsonPointer,
    ):
        """Creates JsonPatch instance based on comparison of two document
        objects. Json patch would be created for `src` argument against `dst`
        one.

        :param src: Data source document object.
        :type src: dict

        :param dst: Data source document object.
        :type dst: dict

        :param dumps: A function of one argument that produces a serialized
                      JSON string.
        :type dumps: function

        :param pointer_cls: JSON pointer class to use.
        :type pointer_cls: Type[JsonPointer]

        :return: :class:`JsonPatch` instance.

        >>> src = {'foo': 'bar', 'numbers': [1, 3, 4, 8]}
        >>> dst = {'baz': 'qux', 'numbers': [1, 4, 7]}
        >>> patch = JsonPatch.from_diff(src, dst)
        >>> new = patch.apply(src)
        >>> new == dst
        True
        """
        json_dumper = dumps or cls.json_dumper
        builder = DiffBuilder(src, dst, json_dumper, pointer_cls=pointer_cls)
        builder._compare_values('', None, src, dst)
        ops = list(builder.execute())
        return cls(ops, pointer_cls=pointer_cls)

    def to_string(self, dumps=None):
        """Returns patch set as JSON string."""
        json_dumper = dumps or self.json_dumper
        return json_dumper(self.patch)

    @property
    def _ops(self):
        return tuple(map(self._get_operation, self.patch))

    def apply(self, obj, in_place=False):
        """Applies the patch to a given object.

        :param obj: Document object.
        :type obj: dict

        :param in_place: Tweaks the way how patch would be applied - directly to
                         specified `obj` or to its copy.
        :type in_place: bool

        :return: Modified `obj`.
        """

        if not in_place:
            obj = copy.deepcopy(obj)

        for operation in self._ops:
            obj = operation.apply(obj)

        return obj

    def _get_operation(self, operation):
        if 'op' not in operation:
            raise InvalidJsonPatch("Operation does not contain 'op' member")

        op = operation['op']

        if not isinstance(op, basestring):
            raise InvalidJsonPatch("Operation's op must be a string")

        if op not in self.operations:
            raise InvalidJsonPatch("Unknown operation {0!r}".format(op))

        cls = self.operations[op]
        return cls(operation, pointer_cls=self.pointer_cls)


class _RebaseNode(object):
    __slots__ = ('id', 'kind', 'value', 'parent', 'key', 'children',
                 'fate', 'written', 'moved', 'applied_ops')

    def __init__(self, node_id, kind, value):
        self.id = node_id
        self.kind = kind
        self.value = value
        self.parent = None
        self.key = None
        self.children = None
        self.fate = 'alive'
        self.written = False
        self.moved = False
        self.applied_ops = set()


class _RebaseGap(object):
    __slots__ = ('id', 'parent')

    def __init__(self, gap_id):
        self.id = gap_id
        self.parent = None


class _Rebaser(object):
    def __init__(self, base, pointer_cls):
        self.pointer_cls = pointer_cls
        self.next_id = 1
        self.target_nodes = {}
        self.target_gaps = {}
        self.origin, self.target = self._build_pair(base)
        self._register_pair(self.origin, self.target)
        self.pending_patch = []
        self.conflicts = []

    def _new_id(self):
        node_id = self.next_id
        self.next_id += 1
        return node_id

    def _build_pair(self, value):
        if isinstance(value, MutableMapping):
            node_id = self._new_id()
            origin = _RebaseNode(node_id, 'object', None)
            target = _RebaseNode(node_id, 'object', None)
            origin_children = {}
            target_children = {}
            for key, child in value.items():
                origin_child, target_child = self._build_pair(child)
                origin_child.parent = origin
                origin_child.key = key
                target_child.parent = target
                target_child.key = key
                origin_children[key] = origin_child
                target_children[key] = target_child
            origin.children = origin_children
            target.children = target_children
            return origin, target

        if isinstance(value, MutableSequence):
            node_id = self._new_id()
            origin = _RebaseNode(node_id, 'array', None)
            target = _RebaseNode(node_id, 'array', None)
            origin_children = []
            target_children = []
            for index, child in enumerate(value):
                gap_id = self._new_id()
                origin_gap = _RebaseGap(gap_id)
                target_gap = _RebaseGap(gap_id)
                origin_gap.parent = origin
                target_gap.parent = target
                origin_children.append(origin_gap)
                target_children.append(target_gap)

                origin_child, target_child = self._build_pair(child)
                origin_child.parent = origin
                origin_child.key = index
                target_child.parent = target
                target_child.key = index
                origin_children.append(origin_child)
                target_children.append(target_child)

            gap_id = self._new_id()
            origin_gap = _RebaseGap(gap_id)
            target_gap = _RebaseGap(gap_id)
            origin_gap.parent = origin
            target_gap.parent = target
            origin_children.append(origin_gap)
            target_children.append(target_gap)
            origin.children = origin_children
            target.children = target_children
            return origin, target

        node_id = self._new_id()
        origin = _RebaseNode(node_id, 'scalar', copy.deepcopy(value))
        target = _RebaseNode(node_id, 'scalar', copy.deepcopy(value))
        return origin, target

    def _wrap_value(self, value, paired=False):
        if isinstance(value, MutableMapping):
            origin = _RebaseNode(None, 'object', None)
            target = _RebaseNode(self._new_id(), 'object', None)
            if paired:
                origin.id = self._new_id()
            origin_children = {}
            target_children = {}
            for key, child in value.items():
                origin_child, target_child = self._wrap_value(child, paired)
                origin_child.parent = origin
                origin_child.key = key
                target_child.parent = target
                target_child.key = key
                origin_children[key] = origin_child
                target_children[key] = target_child
            origin.children = origin_children
            target.children = target_children
            return origin, target

        if isinstance(value, MutableSequence):
            origin = _RebaseNode(None, 'array', None)
            target = _RebaseNode(self._new_id(), 'array', None)
            if paired:
                origin.id = self._new_id()
            origin_children = []
            target_children = []
            for index, child in enumerate(value):
                origin_gap = _RebaseGap(self._new_id())
                target_gap = _RebaseGap(origin_gap.id)
                origin_gap.parent = origin
                target_gap.parent = target
                origin_children.append(origin_gap)
                target_children.append(target_gap)

                origin_child, target_child = self._wrap_value(child, paired)
                origin_child.parent = origin
                origin_child.key = index
                target_child.parent = target
                target_child.key = index
                origin_children.append(origin_child)
                target_children.append(target_child)

            end_origin_gap = _RebaseGap(self._new_id())
            end_target_gap = _RebaseGap(end_origin_gap.id)
            end_origin_gap.parent = origin
            end_target_gap.parent = target
            origin_children.append(end_origin_gap)
            target_children.append(end_target_gap)
            origin.children = origin_children
            target.children = target_children
            return origin, target

        target = _RebaseNode(self._new_id(), 'scalar', copy.deepcopy(value))
        if paired:
            origin = _RebaseNode(self._new_id(), 'scalar', copy.deepcopy(value))
        else:
            origin = _RebaseNode(None, 'scalar', copy.deepcopy(value))
        return origin, target

    def _register_target(self, node):
        self.target_nodes[node.id] = node
        if node.kind == 'object':
            for child in node.children.values():
                self._register_target(child)
        elif node.kind == 'array':
            for child in node.children:
                if isinstance(child, _RebaseNode):
                    self._register_target(child)
                else:
                    child.parent = node
                    self.target_gaps[child.id] = child

    def _redirect_target_identity(self, old_node, new_node, fate):
        self.target_nodes[old_node.id] = new_node
        if old_node.kind == 'object':
            children = old_node.children.values()
        elif old_node.kind == 'array':
            children = (item for item in old_node.children
                        if isinstance(item, _RebaseNode))
        else:
            children = ()
        for child in children:
            self._redirect_target_identity(child, new_node, fate)

    def _register_pair(self, origin, target):
        if origin.id is not None:
            self.target_nodes[origin.id] = target
        if origin.kind in ('object', 'array'):
            if origin.kind == 'object':
                origin_children = origin.children.values()
                target_children = target.children.values()
            else:
                origin_children = origin.children
                target_children = target.children
            for origin_child, target_child in zip(origin_children, target_children):
                if isinstance(origin_child, _RebaseNode):
                    self._register_pair(origin_child, target_child)
                else:
                    self.target_gaps[origin_child.id] = target_child

    def _pointer_parts(self, path):
        if isinstance(path, self.pointer_cls):
            return list(path.parts)
        pointer = self.pointer_cls(path)
        return list(pointer.parts)

    def _array_part(self, parent, part, allow_end=False):
        if part == '-' and allow_end:
            return part
        if not isinstance(part, basestring) or not part or part == '-':
            raise JsonPatchConflict("invalid array index '{0}'".format(part))
        if len(part) > 1 and part[0] == '0':
            raise JsonPatchConflict("invalid array index '{0}'".format(part))
        if not part.isdigit():
            raise JsonPatchConflict("invalid array index '{0}'".format(part))
        index = int(part)
        length = sum(isinstance(item, _RebaseNode) for item in parent.children)
        max_index = length if allow_end else length - 1
        if index > max_index:
            raise JsonPatchConflict("index '{0}' out of bounds".format(index))
        return index

    def _resolve(self, root, path, allow_end=False):
        parts = self._pointer_parts(path)
        node = root
        if not parts:
            return node

        for part in parts:
            if node.kind == 'object':
                if part not in node.children:
                    raise JsonPatchConflict("member '{0}' not found".format(part))
                node = node.children[part]
            else:
                index = self._array_part(node, part, allow_end=False)
                node = self._array_element_at(node, index)

        if node.parent is not None and node.parent.kind == 'array':
            if allow_end:
                length = sum(isinstance(item, _RebaseNode)
                             for item in node.parent.children)
                if node.key == length:
                    return node
        return node

    def _resolve_parent_and_key(self, root, path, allow_end=False):
        parts = self._pointer_parts(path)
        if not parts:
            return root, None

        node = root
        for part in parts[:-1]:
            if node.kind == 'object':
                if part not in node.children:
                    raise JsonPatchConflict(
                        "member '{0}' not found".format(part))
                node = node.children[part]
            else:
                index = self._array_part(node, part)
                node = self._array_element_at(node, index)

        key = parts[-1]
        if node.kind == 'array':
            key = self._array_part(node, key, allow_end=allow_end)
        return node, key

    def _array_element_at(self, array_node, index):
        count = -1
        for item in array_node.children:
            if isinstance(item, _RebaseNode):
                count += 1
                if count == index:
                    return item
        raise JsonPatchConflict("index '{0}' out of bounds".format(index))

    def _array_index_of(self, node):
        index = 0
        for item in node.parent.children:
            if item is node:
                return index
            if isinstance(item, _RebaseNode):
                index += 1
        raise JsonPatchConflict('array element not found')

    def _array_length(self, array_node):
        return sum(isinstance(item, _RebaseNode)
                   for item in array_node.children)

    def _array_gap_for_visible_index(self, array_node, index):
        visible_index = 0
        last_gap = None
        for item in array_node.children:
            if isinstance(item, _RebaseGap):
                last_gap = item
                if visible_index == index:
                    gap = item
                    break
            else:
                visible_index += 1
        else:
            gap = last_gap

        return gap

    def _last_gap_at_visible_index(self, array_node, index):
        gap = self._array_gap_for_visible_index(array_node, index)
        position = array_node.children.index(gap)
        while position + 1 < len(array_node.children):
            following = array_node.children[position + 1]
            if not isinstance(following, _RebaseGap):
                break
            gap = following
            position += 1
        return gap

    def _origin_insert_gap(self, parent, key):
        if key == '-' or key == self._array_length(parent):
            return parent.children[-1]

        anchor = self._array_element_at(parent, key)
        position = parent.children.index(anchor)
        gap = parent.children[position - 1]
        if position >= 2 and isinstance(
                parent.children[position - 2], _RebaseGap):
            gap = parent.children[position - 2]
        return gap

    def _target_path_for_origin_insert_gap(self, origin_parent,
                                           target_parent, key):
        origin_gap = self._origin_insert_gap(origin_parent, key)
        target_gap = self.target_gaps[origin_gap.id]
        transformed_path = self._path_for_gap(target_gap)
        return origin_gap, target_gap, transformed_path

    def _origin_replace_gap(self, node):
        position = node.parent.children.index(node)
        return node.parent.children[position + 1]

    def _path_for(self, node):
        parts = []
        current = node
        while current.parent is not None:
            if current.parent.kind == 'array':
                parts.append(str(self._array_index_of(current)))
            else:
                parts.append(current.key)
            current = current.parent
        parts.reverse()
        return self.pointer_cls.from_parts(parts).path

    def _path_for_gap(self, gap):
        array_node = gap.parent
        visible_index = 0
        for item in array_node.children:
            if item is gap:
                return self._path_for(array_node) + '/' + str(visible_index)
            if isinstance(item, _RebaseNode):
                visible_index += 1
        raise JsonPatchConflict('array gap not found')

    def _materialize(self, node):
        if node.kind == 'scalar':
            return copy.deepcopy(node.value)
        if node.kind == 'object':
            return dict((key, self._materialize(child))
                        for key, child in node.children.items())
        return [self._materialize(item) for item in node.children
                if isinstance(item, _RebaseNode)]

    def _mark_detached(self, node, fate):
        node.fate = fate
        node.parent = None
        node.key = None
        if node.kind == 'object':
            for child in node.children.values():
                self._mark_detached(child, fate)
        elif node.kind == 'array':
            for item in node.children:
                if isinstance(item, _RebaseNode):
                    self._mark_detached(item, fate)

    def _detach_node(self, node, mark_fate=None, applied_index=None):
        parent = node.parent
        position = None
        if parent is None:
            return None, None

        if parent.kind == 'object':
            del parent.children[node.key]
        else:
            children = parent.children
            position = children.index(node)
            del children[position]

        node.parent = None
        node.key = None

        if mark_fate is not None:
            self._mark_detached(node, mark_fate)
            if applied_index is not None:
                self._mark_detached_op(node, mark_fate, applied_index)
        return parent, position

    def _mark_detached_op(self, node, fate, applied_index):
        node.applied_ops.add(applied_index)
        if node.kind == 'object':
            for child in node.children.values():
                self._mark_detached_op(child, fate, applied_index)
        elif node.kind == 'array':
            for item in node.children:
                if isinstance(item, _RebaseNode):
                    self._mark_detached_op(item, fate, applied_index)

    def _mark_written(self, node, applied_index):
        node.written = True
        node.applied_ops.add(applied_index)

    def _mark_written_tree(self, node, applied_index):
        self._mark_written(node, applied_index)
        if node.kind == 'object':
            for child in node.children.values():
                self._mark_written_tree(child, applied_index)
        elif node.kind == 'array':
            for child in node.children:
                if isinstance(child, _RebaseNode):
                    self._mark_written_tree(child, applied_index)

    def _mark_moved(self, node, applied_index):
        node.moved = True
        node.applied_ops.add(applied_index)

    def _attach_object(self, parent, key, node):
        old_node = parent.children.get(key)
        parent.children[key] = node
        node.parent = parent
        node.key = key
        return old_node

    def _attach_array_before_gap(self, gap, node):
        parent = gap.parent
        position = parent.children.index(gap)
        parent.children.insert(position, node)
        node.parent = parent
        self._reindex_array(parent)

    def _attach_array_at_index(self, parent, index, node):
        gap = self._array_gap_for_visible_index(parent, index)
        self._attach_array_before_gap(gap, node)
        return gap

    def _reindex_array(self, array_node):
        index = 0
        for item in array_node.children:
            if isinstance(item, _RebaseNode):
                item.key = index
                index += 1

    def _replace_root(self, node, fate='replaced'):
        old_root = self.target
        self._mark_detached(old_root, fate)
        self.target = node
        node.parent = None
        node.key = None

    def _replace_node_target(self, node, new_node):
        parent = node.parent
        if parent is None:
            self._replace_root(new_node)
            return

        if parent.kind == 'object':
            parent.children[node.key] = new_node
            new_node.parent = parent
            new_node.key = node.key
        else:
            position = node.parent.children.index(node)
            gap = node.parent.children[position + 1]
            self._detach_node(node, 'replaced')
            self._attach_array_before_gap(gap, new_node)

    def _replace_node_pair(self, node, origin_node, target_node):
        parent = node.parent
        if parent is None:
            old_origin = self.origin
            old_target = self.target
            self._mark_detached(old_origin, 'replaced')
            self._mark_detached(old_target, 'replaced')
            self.origin = origin_node
            self.target = target_node
            origin_node.parent = None
            target_node.parent = None
            return

        if parent.kind == 'object':
            key = node.key
            parent.children[key] = origin_node
            origin_node.parent = parent
            origin_node.key = key

            target_parent = self.target_nodes[parent.id]
            target_parent.children[key] = target_node
            target_node.parent = target_parent
            target_node.key = key
        else:
            origin_position = parent.children.index(node)
            origin_gap = parent.children[origin_position + 1]
            target_gap = self.target_gaps[origin_gap.id]
            self._detach_node(node, 'replaced')
            self._attach_array_before_gap(origin_gap, origin_node)

            target_node_old = self.target_nodes[node.id]
            self._detach_node(target_node_old, 'replaced')
            self._attach_array_before_gap(target_gap, target_node)

    def _descendant_has_applied_change(self, node):
        if node.kind == 'object':
            return any(self._descendant_has_applied_change(child)
                       for child in node.children.values())
        if node.kind == 'array':
            return any(self._descendant_has_applied_change(item)
                       for item in node.children
                        if isinstance(item, _RebaseNode))
        return False

    def _descendant_has_real_change(self, node):
        if node.kind == 'object':
            return any(child.written or child.moved or
                       self._descendant_has_real_change(child)
                       for child in node.children.values())
        if node.kind == 'array':
            return any(item.written or item.moved or
                       self._descendant_has_real_change(item)
                       for item in node.children
                       if isinstance(item, _RebaseNode))
        return False

    def _has_applied_change(self, node):
        return node.written or node.moved or \
            self._descendant_has_applied_change(node)

    def _conflict(self, index, operation, reason, path=None, from_path=None,
                  applied_index=None, detail=None):
        conflict = {
            'operation_index': index,
            'op': operation.get('op'),
            'reason': reason,
        }
        if path is not None:
            conflict['path'] = path
        if from_path is not None:
            conflict['from'] = from_path
        if applied_index is not None:
            conflict['applied_operation_index'] = applied_index
        if detail is not None:
            conflict['detail'] = detail
        self.conflicts.append(conflict)

    def apply_applied(self, operation, index):
        op = operation['op']
        if op == 'add':
            return self._applied_add(operation, index)
        if op == 'remove':
            return self._applied_remove(operation, index)
        if op == 'replace':
            return self._applied_replace(operation, index)
        if op == 'move':
            return self._applied_move(operation, index)
        if op == 'copy':
            return self._applied_copy(operation, index)
        return None

    def _applied_add(self, operation, index):
        new_node = self._wrap_value(operation['value'], paired=False)[1]
        new_node.applied_ops.add(index)
        parent, key = self._resolve_parent_and_key(
            self.target, operation['path'], allow_end=True)

        if parent is self.target and key is None:
            self._replace_root(new_node)
            self._register_target(new_node)
            return

        if parent.kind == 'object':
            old_node = self._attach_object(parent, key, new_node)
            if old_node is not None:
                self._mark_detached(old_node, 'replaced')
                self._mark_written_tree(new_node, index)
        else:
            if key == '-':
                gap = parent.children[-1]
                self._attach_array_before_gap(gap, new_node)
            else:
                self._attach_array_at_index(parent, key, new_node)
        self._register_target(new_node)

    def _applied_remove(self, operation, index):
        node = self._resolve(self.target, operation['path'])
        if node.parent is None:
            raise InvalidJsonPatch("can't remove the document root")

        parent = node.parent
        self._detach_node(node, 'removed', index)
        if parent.kind == 'array':
            self._reindex_array(parent)
    def _applied_replace(self, operation, index):
        new_node = self._wrap_value(operation['value'], paired=False)[1]
        node = self._resolve(self.target, operation['path'])
        if self._materialize(node) != operation['value']:
            self._mark_written_tree(new_node, index)

        if node.parent is None:
            self._replace_root(new_node)
            self._redirect_target_identity(node, new_node, 'replaced')
            self._register_target(new_node)
            return

        parent = node.parent
        if parent.kind == 'object':
            parent.children[node.key] = new_node
            new_node.parent = parent
            new_node.key = node.key
        else:
            position = parent.children.index(node)
            gap = parent.children[position + 1]
            self._detach_node(node, 'replaced')
            self._attach_array_before_gap(gap, new_node)

        self._redirect_target_identity(node, new_node, 'replaced')
        self._register_target(new_node)

    def _applied_move(self, operation, index):
        source = self._resolve(self.target, operation['from'])
        if source.parent is None:
            raise JsonPatchConflict("can't move the document root")

        if operation['from'] == operation['path']:
            return

        source_parent = source.parent
        source_key = source.key
        if source_parent.kind == 'array':
            source_index = source.key
            parent_children = source_parent.children
            source_position = parent_children.index(source)
            del parent_children[source_position]
            source.parent = None
            source.key = None
            self._reindex_array(source_parent)
        else:
            del source_parent.children[source_key]
            source.parent = None
            source.key = None

        parent, key = self._resolve_parent_and_key(
            self.target, operation['path'], allow_end=True)
        if parent is self.target and key is None:
            self._replace_root(source)
        elif parent.kind == 'object':
            old_node = self._attach_object(parent, key, source)
            if old_node is not None:
                self._mark_detached(old_node, 'replaced')
        else:
            if key == '-':
                self._attach_array_before_gap(parent.children[-1], source)
            elif parent is source_parent:
                target_index = key if key <= source_index else key - 1
                gap = self._array_gap_for_visible_index(parent, target_index)
                self._attach_array_before_gap(gap, source)
            else:
                self._attach_array_at_index(parent, key, source)

        self._mark_moved(source, index)

    def _applied_copy(self, operation, index):
        source = self._resolve(self.target, operation['from'])
        value = self._materialize(source)
        copy_operation = dict(operation)
        copy_operation['value'] = value
        self._applied_add(copy_operation, index)

    def apply_pending(self, operation, index):
        op = operation['op']
        try:
            if op == 'add':
                self._pending_add(operation, index)
            elif op == 'remove':
                self._pending_remove(operation, index)
            elif op == 'replace':
                self._pending_replace(operation, index)
            elif op == 'move':
                self._pending_move(operation, index)
            elif op == 'copy':
                self._pending_copy(operation, index)
            elif op == 'test':
                self._pending_test(operation, index)
        except JsonPatchConflict as exception:
            if exception.args and (
                    "member '" in exception.args[0] or
                    'index ' in exception.args[0]):
                self._conflict(index, operation, 'path_not_in_base',
                               path=operation.get('path'),
                               from_path=operation.get('from'))
                return
            if op in ('replace', 'remove', 'add', 'test') and \
                    self._conflict_for_resolution(
                        index, operation, self.origin, operation.get('path')):
                return
            if op in ('move', 'copy') and \
                    self._conflict_for_resolution(
                        index, operation, self.origin, operation.get('from'),
                        from_path=operation.get('from')):
                return
            self._conflict(index, operation, 'unresolvable_patch',
                           path=operation.get('path'),
                           from_path=operation.get('from'),
                           detail=str(exception))

    def _set_pair_root(self, origin_node, target_node, fate='pending_replaced'):
        self._mark_detached(self.origin, fate)
        self._mark_detached(self.target, fate)
        self.origin = origin_node
        self.target = target_node
        origin_node.parent = None
        target_node.parent = None

    def _set_pair_object_child(self, origin_parent, target_parent, key,
                               origin_node, target_node):
        old_origin = origin_parent.children.get(key)
        old_target = None
        if old_origin is not None:
            old_target = self.target_nodes[old_origin.id]

        origin_parent.children[key] = origin_node
        origin_node.parent = origin_parent
        origin_node.key = key

        target_parent.children[key] = target_node
        target_node.parent = target_parent
        target_node.key = key
        return old_origin, old_target

    def _insert_pair_before_origin_gap(self, origin_gap, origin_node,
                                       target_node):
        target_gap = self.target_gaps[origin_gap.id]
        self._attach_array_before_gap(origin_gap, origin_node)
        self._attach_array_before_gap(target_gap, target_node)

    def _insert_pair_at_origin_coordinate(self, origin_parent, target_parent,
                                          key, origin_node, target_node):
        origin_gap = self._origin_insert_gap(origin_parent, key)
        target_gap = self.target_gaps[origin_gap.id]
        self._attach_array_before_gap(origin_gap, origin_node)
        self._attach_array_before_gap(target_gap, target_node)
        self._register_pair(origin_node, target_node)
        return self._path_for(target_node)

    def _map_existing_node(self, origin_node):
        try:
            target_node = self.target_nodes[origin_node.id]
        except KeyError:
            raise JsonPatchConflict('node was removed')
        return target_node

    def _conflict_for_resolution(self, index, operation, root, path,
                                 from_path=None):
        parts = self._pointer_parts(path)
        current = root
        for part in parts:
            try:
                if current.kind == 'object' and part not in current.children:
                    return False
                if current.kind == 'array':
                    index_value = self._array_part(current, part)
                    current = self._array_element_at(current, index_value)
                else:
                    current = current.children[part]

                target = self.target_nodes.get(current.id)
                if target is None:
                    return False
                if target.fate == 'removed':
                    applied_index = min(target.applied_ops) \
                        if target.applied_ops else None
                    self._structural_conflict(
                        index, operation, target, 'ancestor_removed',
                        path=path, from_path=from_path,
                        applied_index=applied_index)
                    return True
                if target.fate == 'replaced':
                    applied_index = min(target.applied_ops) \
                        if target.applied_ops else None
                    self._structural_conflict(
                        index, operation, target, 'ancestor_replaced',
                        path=path, from_path=from_path,
                        applied_index=applied_index)
                    return True
            except JsonPatchConflict:
                return False
        return False

    def _structural_conflict(self, index, operation, target_node, reason,
                             path=None, from_path=None):
        applied_index = min(target_node.applied_ops) if \
            target_node.applied_ops else None
        self._conflict(index, operation, reason, path=path,
                       from_path=from_path, applied_index=applied_index)

    def _applied_value_matches(self, origin_node, target_node):
        return self._materialize(origin_node) == \
            self._materialize(target_node)

    def _add_operation(self, operation, transformed=None):
        transformed = transformed if transformed is not None else operation
        result = copy.deepcopy(transformed)
        self.pending_patch.append(result)
        return result

    def _pending_add(self, operation, index):
        origin_value = copy.deepcopy(operation['value'])
        origin_new, target_new = self._wrap_value(origin_value, paired=True)
        origin_parent, key = self._resolve_parent_and_key(
            self.origin, operation['path'], allow_end=True)
        target_parent = self._map_existing_node(origin_parent)
        if target_parent.fate != 'alive':
            self._structural_conflict(
                index, operation, target_parent,
                'ancestor_removed' if target_parent.fate == 'removed'
                else 'ancestor_replaced',
                path=operation.get('path'))
            return
        if target_parent.written:
            reason = 'root_replaced' if origin_parent is self.origin \
                else 'ancestor_replaced'
            self._structural_conflict(index, operation, target_parent,
                                      reason, path=operation.get('path'))
            return

        if origin_parent is self.origin and key is None:
            if self._has_applied_change(self.target):
                self._structural_conflict(
                    index, operation, self.target, 'root_replaced',
                    path=operation.get('path'))
                return
            self._set_pair_root(origin_new, target_new)
            self._register_pair(origin_new, target_new)
            self._add_operation(operation, {'op': 'add', 'path': '',
                                            'value': origin_value})
            return

        if origin_parent.kind == 'object':
            existing = origin_parent.children.get(key)
            target_parent = self._map_existing_node(origin_parent)
            target_existing = target_parent.children.get(key)
            if existing is None and target_existing is not None:
                self._structural_conflict(
                    index, operation, target_existing,
                    'object_key_added_by_both',
                    path=self._path_for(target_existing))
                return
            if existing is not None:
                if target_existing.written:
                    self._structural_conflict(
                        index, operation, target_existing,
                        'same_scalar_written',
                        path=self._path_for(target_existing))
                    return
            elif key not in target_parent.children:
                target_parent = self._map_existing_node(origin_parent)

            old_origin, old_target = self._set_pair_object_child(
                origin_parent, target_parent, key, origin_new, target_new)
            if old_origin is not None:
                self._mark_detached(old_origin, 'replaced')
                self._mark_detached(old_target, 'replaced')

            self._register_pair(origin_new, target_new)
            self._add_operation(operation, {'op': 'add',
                                            'path': self._path_for(target_new),
                                            'value': origin_value})
            return

        transformed_path = self._insert_pair_at_origin_coordinate(
            origin_parent, target_parent, key, origin_new, target_new)
        self._add_operation(operation, {'op': 'add',
                                        'path': transformed_path,
                                        'value': origin_value})

    def _pending_remove(self, operation, index):
        origin_node = self._resolve(self.origin, operation['path'])
        target_node = self._map_existing_node(origin_node)
        transformed_path = self._path_for(target_node)

        if target_node.fate == 'removed':
            return

        if target_node.fate == 'replaced':
            self._structural_conflict(index, operation, target_node,
                                      'ancestor_replaced',
                                      path=operation.get('path'))
            return

        if target_node.moved:
            self._structural_conflict(index, operation, target_node,
                                      'moved_node_removed',
                                      path=transformed_path)
            return
        if target_node.written:
            self._structural_conflict(index, operation, target_node,
                                      'same_scalar_written',
                                      path=self._path_for(target_node))
            return
        elif self._descendant_has_applied_change(target_node):
            self._structural_conflict(
                index, operation, target_node,
                'ancestor_removed_while_descendant_changed',
                path=self._path_for(target_node))
            return

        if origin_node.parent is None:
            raise InvalidJsonPatch("can't remove the document root")

        origin_parent = origin_node.parent
        target_parent = target_node.parent
        self._detach_node(origin_node, 'pending_removed')
        self._detach_node(target_node, 'pending_removed')
        if origin_parent is not None and origin_parent.kind == 'array':
            self._reindex_array(origin_parent)
        if target_parent is not None and target_parent.kind == 'array':
            self._reindex_array(target_parent)

        self._add_operation(operation, {'op': 'remove',
                                        'path': transformed_path})

    def _pending_replace(self, operation, index):
        origin_node = self._resolve(self.origin, operation['path'])
        target_node = self._map_existing_node(origin_node)

        if target_node.fate == 'replaced':
            self._structural_conflict(index, operation, target_node,
                                      'ancestor_replaced',
                                      path=operation.get('path'))
            return

        if target_node.fate == 'removed':
            self._structural_conflict(index, operation, target_node,
                                      'ancestor_removed',
                                      path=operation.get('path'))
            return

        pure_move = target_node.moved and not target_node.written and not \
            self._descendant_has_real_change(target_node)
        if (target_node.written or
                self._descendant_has_applied_change(target_node)) and \
                not pure_move:
            self._structural_conflict(
                index, operation, target_node,
                'test_premise_changed' if operation['op'] == 'test'
                else 'same_scalar_written',
                path=self._path_for(target_node))
            return

        origin_value = copy.deepcopy(operation['value'])
        origin_new, target_new = self._wrap_value(origin_value, paired=True)

        if origin_node.parent is None:
            self._set_pair_root(origin_new, target_new)
            transformed_path = ''
        elif origin_node.parent.kind == 'object':
            key = origin_node.key
            self._set_pair_object_child(
                origin_node.parent, target_node.parent, key,
                origin_new, target_new)
            self._mark_detached(origin_node, 'pending_replaced')
            self._mark_detached(target_node, 'pending_replaced')
            transformed_path = self._path_for(target_new)
        else:
            origin_parent = origin_node.parent
            target_parent = target_node.parent
            origin_gap = self._origin_replace_gap(origin_node)
            target_gap = self.target_gaps[origin_gap.id]

            self._detach_node(origin_node, 'pending_replaced')
            self._attach_array_before_gap(origin_gap, origin_new)
            self._detach_node(target_node, 'pending_replaced')
            self._reindex_array(target_parent)
            transformed_path = self._path_for_gap(target_gap)
            self._attach_array_before_gap(target_gap, target_new)

        self._register_pair(origin_new, target_new)
        self._add_operation(operation, {'op': 'replace',
                                        'path': transformed_path,
                                        'value': origin_value})

    def _detach_origin_target_pair(self, origin_node, target_node,
                                   fate='pending_removed'):
        origin_parent = origin_node.parent
        target_parent = target_node.parent

        self._detach_node(origin_node, fate)
        self._detach_node(target_node, fate)
        if origin_parent is not None and origin_parent.kind == 'array':
            self._reindex_array(origin_parent)
        if target_parent is not None and target_parent.kind == 'array':
            self._reindex_array(target_parent)

        return origin_parent, target_parent

    def _pending_move(self, operation, index):
        origin_source = self._resolve(self.origin, operation['from'])
        target_source = self._map_existing_node(origin_source)

        if target_source.fate == 'removed':
            self._structural_conflict(index, operation, target_source,
                                      'ancestor_removed',
                                      path=operation.get('path'),
                                      from_path=operation.get('from'))
            return

        if target_source.fate == 'replaced':
            self._structural_conflict(index, operation, target_source,
                                      'ancestor_replaced',
                                      path=operation.get('path'),
                                      from_path=operation.get('from'))
            return

        if operation['from'] == operation['path']:
            return

        if target_source.moved:
            self._structural_conflict(index, operation, target_source,
                                      'moved_node_moved',
                                      path=operation.get('path'),
                                      from_path=self._path_for(target_source))
            return

        origin_parent, key = self._resolve_parent_and_key(
            self.origin, operation['path'], allow_end=True)
        target_parent = self._map_existing_node(origin_parent)
        if target_parent.fate != 'alive':
            self._structural_conflict(
                index, operation, target_parent,
                'ancestor_removed' if target_parent.fate == 'removed'
                else 'ancestor_replaced',
                path=operation.get('path'),
                from_path=operation.get('from'))
            return

        if origin_parent is self.origin and key is None:
            self._structural_conflict(index, operation, self.target,
                                      'root_replaced',
                                      path='',
                                      from_path=operation.get('from'))
            return

        existing_destination = None
        if origin_parent.kind == 'object':
            existing_destination = origin_parent.children.get(key)

        transformed_from = self._path_for(target_source)

        same_array_move = origin_source.parent is not None and \
            target_source.parent is not None and \
            origin_source.parent.id == origin_parent.id and \
            target_source.parent.id == target_parent.id and \
            origin_parent.kind == 'array' and \
            target_parent.kind == 'array'

        if same_array_move:
            origin_gap = self._same_array_move_gap(
                origin_parent, origin_source, key)
            target_gap = self.target_gaps[origin_gap.id]

            self._detach_node(origin_source)
            self._reindex_array(origin_parent)
            self._detach_node(target_source)
            self._reindex_array(target_parent)
            transformed_path = self._path_for_gap(target_gap)
            self._attach_array_before_gap(origin_gap, origin_source)
            self._attach_array_before_gap(target_gap, target_source)

        elif origin_parent.kind == 'array':
            origin_gap, target_gap, _ = \
                self._target_path_for_origin_insert_gap(
                    origin_parent, target_parent, key)
            destination_index = self._array_length(target_parent) \
                if key == '-' else key
            self._detach_origin_target_pair(origin_source, target_source)
            gap_selector = self._last_gap_at_visible_index \
                if key == '-' else self._array_gap_for_visible_index
            target_gap = gap_selector(
                target_parent, destination_index)
            transformed_path = self._path_for_gap(target_gap)
            self._attach_array_before_gap(origin_gap, origin_source)
            self._attach_array_before_gap(target_gap, target_source)

        else:
            existing_target_destination = None
            if existing_destination is not None:
                existing_target_destination = \
                    self.target_nodes[existing_destination.id]
                if existing_target_destination.written:
                    self._structural_conflict(
                        index, operation, existing_target_destination,
                        'same_scalar_written',
                        path=self._path_for(existing_target_destination),
                        from_path=operation.get('from'))
                    return

            transformed_path = self._path_for(target_parent) + '/' + \
                self.pointer_cls.from_parts([key]).path[1:]

            self._detach_origin_target_pair(origin_source, target_source)

            old_origin, old_target = self._set_pair_object_child(
                origin_parent, target_parent, key,
                origin_source, target_source)
            if old_origin is not None:
                self._mark_detached(old_origin, 'replaced')
                self._mark_detached(old_target, 'replaced')

        result = copy.deepcopy(operation)
        result['from'] = transformed_from
        result['path'] = transformed_path
        self.pending_patch.append(result)

    def _same_array_move_gap(self, array_node, source_node, key):
        source_index = source_node.key
        length = sum(isinstance(item, _RebaseNode)
                     for item in array_node.children)
        if key == '-':
            raw_index = length
        else:
            raw_index = key

        desired_index = raw_index if raw_index <= source_index \
            else raw_index - 1
        return self._array_gap_for_visible_index(array_node, desired_index)

    def _pending_copy(self, operation, index):
        origin_source = self._resolve(self.origin, operation['from'])
        target_source = self._map_existing_node(origin_source)

        if target_source.fate in ('removed', 'replaced'):
            self._structural_conflict(index, operation, target_source,
                                      'copy_source_unavailable',
                                      path=operation.get('path'),
                                      from_path=operation.get('from'))
            return

        pure_move = target_source.moved and not target_source.written and \
            not self._descendant_has_real_change(target_source)
        if (target_source.written or
                self._descendant_has_applied_change(target_source)) and \
                not pure_move:
            self._structural_conflict(index, operation, target_source,
                                      'copy_source_changed',
                                      path=operation.get('path'),
                                      from_path=self._path_for(target_source))
            return

        origin_parent, key = self._resolve_parent_and_key(
            self.origin, operation['path'], allow_end=True)
        target_parent = self._map_existing_node(origin_parent)
        if target_parent.fate != 'alive':
            self._structural_conflict(
                index, operation, target_parent,
                'ancestor_removed' if target_parent.fate == 'removed'
                else 'ancestor_replaced',
                path=operation.get('path'),
                from_path=operation.get('from'))
            return

        if origin_parent is self.origin and key is None:
            self._structural_conflict(index, operation, self.target,
                                      'root_replaced', path='',
                                      from_path=operation.get('from'))
            return

        origin_value = self._materialize(origin_source)
        origin_new, target_new = self._wrap_value(origin_value, paired=True)

        if origin_parent.kind == 'object':
            existing = origin_parent.children.get(key)
            if existing is not None:
                target_existing = self.target_nodes[existing.id]
                if target_existing.written:
                    self._structural_conflict(
                        index, operation, target_existing,
                        'same_scalar_written',
                        path=self._path_for(target_existing),
                        from_path=operation.get('from'))
                    return

            old_origin, old_target = self._set_pair_object_child(
                origin_parent, target_parent, key, origin_new, target_new)
            if old_origin is not None:
                self._mark_detached(old_origin, 'replaced')
                self._mark_detached(old_target, 'replaced')
            transformed_path = self._path_for(target_new)
        else:
            transformed_path = self._insert_pair_at_origin_coordinate(
                origin_parent, target_parent, key, origin_new, target_new)

        self._register_pair(origin_new, target_new)
        self._add_operation(operation, {'op': 'copy',
                                        'from': self._path_for(target_source),
                                        'path': transformed_path})

    def _pending_test(self, operation, index):
        origin_node = self._resolve(self.origin, operation['path'])
        target_node = self._map_existing_node(origin_node)

        if target_node.fate == 'removed':
            self._structural_conflict(index, operation, target_node,
                                      'test_premise_changed',
                                      path=operation.get('path'))
            return

        if target_node.fate == 'replaced':
            self._structural_conflict(index, operation, target_node,
                                      'test_premise_changed',
                                      path=operation.get('path'))
            return

        if not self._applied_value_matches(origin_node, target_node):
            self._structural_conflict(index, operation, target_node,
                                      'test_premise_changed',
                                      path=self._path_for(target_node))
            return

        transformed_path = self._path_for(target_node)
        self._add_operation(operation, {'op': 'test',
                                        'path': transformed_path,
                                        'value': copy.deepcopy(
                                            operation['value'])})


class DiffBuilder(object):

    def __init__(self, src_doc, dst_doc, dumps=json.dumps, pointer_cls=JsonPointer):
        self.dumps = dumps
        self.pointer_cls = pointer_cls
        self.index_storage = [{}, {}]
        self.index_storage2 = [[], []]
        self.__root = root = []
        self.src_doc = src_doc
        self.dst_doc = dst_doc
        root[:] = [root, root, None]

    def store_index(self, value, index, st):
        typed_key = (value, type(value))
        try:
            storage = self.index_storage[st]
            stored = storage.get(typed_key)
            if stored is None:
                storage[typed_key] = [index]
            else:
                storage[typed_key].append(index)

        except TypeError:
            self.index_storage2[st].append((typed_key, index))

    def take_index(self, value, st):
        typed_key = (value, type(value))
        try:
            stored = self.index_storage[st].get(typed_key)
            if stored:
                return stored.pop()

        except TypeError:
            storage = self.index_storage2[st]
            for i in range(len(storage)-1, -1, -1):
                if storage[i][0] == typed_key:
                    return storage.pop(i)[1]

    def insert(self, op):
        root = self.__root
        last = root[0]
        last[1] = root[0] = [last, root, op]
        return root[0]

    def remove(self, index):
        link_prev, link_next, _ = index
        link_prev[1] = link_next
        link_next[0] = link_prev
        index[:] = []

    def iter_from(self, start):
        root = self.__root
        curr = start[1]
        while curr is not root:
            yield curr[2]
            curr = curr[1]

    def __iter__(self):
        root = self.__root
        curr = root[1]
        while curr is not root:
            yield curr[2]
            curr = curr[1]

    def execute(self):
        root = self.__root
        curr = root[1]
        while curr is not root:
            if curr[1] is not root:
                op_first, op_second = curr[2], curr[1][2]
                if op_first.location == op_second.location and \
                        type(op_first) == RemoveOperation and \
                        type(op_second) == AddOperation:
                    yield ReplaceOperation({
                        'op': 'replace',
                        'path': op_second.location,
                        'value': op_second.operation['value'],
                    }, pointer_cls=self.pointer_cls).operation
                    curr = curr[1][1]
                    continue

            yield curr[2].operation
            curr = curr[1]

    def _item_added(self, path, key, item):
        index = self.take_index(item, _ST_REMOVE)
        if index is not None:
            op = index[2]
            if type(op.key) == int and type(key) == int:
                for v in self.iter_from(index):
                    op.key = v._on_undo_remove(op.path, op.key)

            self.remove(index)
            if op.location != _path_join(path, key):
                new_op = MoveOperation({
                    'op': 'move',
                    'from': op.location,
                    'path': _path_join(path, key),
                }, pointer_cls=self.pointer_cls)
                self.insert(new_op)
        else:
            new_op = AddOperation({
                'op': 'add',
                'path': _path_join(path, key),
                'value': item,
            }, pointer_cls=self.pointer_cls)
            new_index = self.insert(new_op)
            self.store_index(item, new_index, _ST_ADD)

    def _item_removed(self, path, key, item):
        new_op = RemoveOperation({
            'op': 'remove',
            'path': _path_join(path, key),
        }, pointer_cls=self.pointer_cls)
        index = self.take_index(item, _ST_ADD)
        new_index = self.insert(new_op)
        if index is not None:
            op = index[2]
            # We can't rely on the op.key type since PatchOperation casts
            # the .key property to int and this path wrongly ends up being taken
            # for numeric string dict keys while the intention is to only handle lists.
            # So we do an explicit check on the item affected by the op instead.
            added_item = op.pointer.to_last(self.dst_doc)[0]
            if type(added_item) == list:
                for v in self.iter_from(index):
                    op.key = v._on_undo_add(op.path, op.key)

            self.remove(index)
            if new_op.location != op.location:
                new_op = MoveOperation({
                    'op': 'move',
                    'from': new_op.location,
                    'path': op.location,
                }, pointer_cls=self.pointer_cls)
                new_index[2] = new_op

            else:
                self.remove(new_index)

        else:
            self.store_index(item, new_index, _ST_REMOVE)

    def _item_replaced(self, path, key, item):
        self.insert(ReplaceOperation({
            'op': 'replace',
            'path': _path_join(path, key),
            'value': item,
        }, pointer_cls=self.pointer_cls))

    def _compare_dicts(self, path, src, dst):
        src_keys = set(src.keys())
        dst_keys = set(dst.keys())
        added_keys = dst_keys - src_keys
        removed_keys = src_keys - dst_keys

        for key in removed_keys:
            self._item_removed(path, str(key), src[key])

        for key in added_keys:
            self._item_added(path, str(key), dst[key])

        for key in src_keys & dst_keys:
            self._compare_values(path, key, src[key], dst[key])

    def _compare_lists(self, path, src, dst):
        len_src, len_dst = len(src), len(dst)
        max_len = max(len_src, len_dst)
        min_len = min(len_src, len_dst)
        for key in range(max_len):
            if key < min_len:
                old, new = src[key], dst[key]
                if old == new:
                    continue

                elif isinstance(old, MutableMapping) and \
                    isinstance(new, MutableMapping):
                    self._compare_dicts(_path_join(path, key), old, new)

                elif isinstance(old, MutableSequence) and \
                        isinstance(new, MutableSequence):
                    self._compare_lists(_path_join(path, key), old, new)

                else:
                    self._item_removed(path, key, old)
                    self._item_added(path, key, new)

            elif len_src > len_dst:
                self._item_removed(path, len_dst, src[key])

            else:
                self._item_added(path, key, dst[key])

    def _compare_values(self, path, key, src, dst):
        if isinstance(src, MutableMapping) and \
                isinstance(dst, MutableMapping):
            self._compare_dicts(_path_join(path, key), src, dst)

        elif isinstance(src, MutableSequence) and \
                isinstance(dst, MutableSequence):
            self._compare_lists(_path_join(path, key), src, dst)

        # To ensure we catch changes to JSON, we can't rely on a simple
        # src == dst, because it would not recognize the difference between
        # 1 and True, among other things. Using json.dumps is the most
        # fool-proof way to ensure we catch type changes that matter to JSON
        # and ignore those that don't. The performance of this could be
        # improved by doing more direct type checks, but we'd need to be
        # careful to accept type changes that don't matter when JSONified.
        elif self.dumps(src) == self.dumps(dst):
            return

        else:
            self._item_replaced(path, key, dst)


def _path_join(path, key):
    if key is None:
        return path

    return path + '/' + str(key).replace('~', '~0').replace('/', '~1')
