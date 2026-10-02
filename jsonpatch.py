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


class RebaseConflict(dict):
    """Structured description of a patch operation that cannot be rebased."""

    def __init__(self, operation_index, path, reason, operation, from_path=None,
                 applied_operation_indexes=None):
        data = {
            'operation_index': operation_index,
            'path': path,
            'reason': reason,
            'operation': copy.deepcopy(operation),
        }
        if from_path is not None:
            data['from'] = from_path
        if applied_operation_indexes:
            data['applied_operation_indexes'] = list(
                applied_operation_indexes)
        super(RebaseConflict, self).__init__(data)
        self.__dict__.update(data)

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class RebaseResult(list):
    """Result of rebasing one JSON Patch on top of another."""

    def __init__(self, patch, conflicts):
        super(RebaseResult, self).__init__(copy.deepcopy(patch))
        self.patch = list(self)
        self.conflicts = copy.deepcopy(conflicts)

    @property
    def ok(self):
        return not self.conflicts

    def apply(self, doc, in_place=False):
        if self.conflicts:
            raise JsonPatchConflict('Cannot apply a patch with rebase conflicts')
        return JsonPatch(self.patch).apply(doc, in_place=in_place)

    def to_dict(self):
        return {
            'patch': list(self),
            'conflicts': copy.deepcopy(self.conflicts),
        }


def rebase(base, applied, pending):
    """Rebase ``pending`` so that it can be applied after ``applied``.

    The three input values are not modified. A successful result contains a
    new patch in :attr:`RebaseResult.patch`. When an operation has no unique
    rebasing, :attr:`RebaseResult.conflicts` contains structured conflict
    information.
    """
    return _Rebaser(base, applied, pending).run()


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


class _IdentityNode(object):
    def __init__(self, raw, node_id, parent=None, key=None,
                 changed_by=None, moved_by=None):
        self.raw = raw
        self.id = node_id
        self.parent = parent
        self.key = key
        self.changed_by = set(changed_by or ())
        self.moved_by = set(moved_by or ())
        self.direct_moved_by = set()
        self.tombstoned_by = set()
        self.tombstone_reason = ''

    def _clone(self, new_id=None, changed_by=None, moved_by=None):
        if new_id is None:
            new_id = self.id
        return _IdentityNode(
            copy.deepcopy(self.raw), new_id, None, None,
            set(changed_by if changed_by is not None else self.changed_by),
            set(moved_by if moved_by is not None else self.moved_by))


class _IdentityState(object):
    def __init__(self, doc, root_id=('base',)):
        self.next_id = 0
        self.root = self._build(copy.deepcopy(doc), root_id, None, None)
        self.tombstones = {}
        self.nodes_by_id = {}
        self._index_subtree(self.root)

    def _build(self, raw, node_id, parent, key, changed_by=None,
               moved_by=None, tombstoned_by=None, tombstone_reason=''):
        node = _IdentityNode(raw, node_id, parent, key,
                             changed_by=changed_by, moved_by=moved_by)
        if tombstoned_by:
            node.tombstoned_by = set(tombstoned_by)
            node.tombstone_reason = tombstone_reason
        if isinstance(raw, MutableMapping):
            children = {}
            for child_key, child_raw in raw.items():
                child_id = node_id + ('dict', child_key)
                children[child_key] = self._build(
                    child_raw, child_id, node, child_key,
                    changed_by=changed_by, moved_by=moved_by,
                    tombstoned_by=tombstoned_by,
                    tombstone_reason=tombstone_reason)
            node.children = children
        elif isinstance(raw, MutableSequence):
            children = []
            for index, child_raw in enumerate(raw):
                child_id = node_id + ('list', index)
                children.append(self._build(
                    child_raw, child_id, node, index,
                    changed_by=changed_by, moved_by=moved_by,
                    tombstoned_by=tombstoned_by,
                    tombstone_reason=tombstone_reason))
            node.children = children
        return node

    def _index_subtree(self, node):
        stack = [node]
        while stack:
            current = stack.pop()
            self.nodes_by_id[current.id] = current
            if isinstance(current.raw, MutableMapping):
                stack.extend(current.children.values())
            elif isinstance(current.raw, MutableSequence):
                stack.extend(current.children)

    def _unindex_subtree(self, node):
        stack = [node]
        while stack:
            current = stack.pop()
            self.nodes_by_id.pop(current.id, None)
            if isinstance(current.raw, MutableMapping):
                stack.extend(current.children.values())
            elif isinstance(current.raw, MutableSequence):
                stack.extend(current.children)

    def find_id(self, node_id):
        return self.nodes_by_id.get(node_id)

    def snapshot(self):
        return copy.deepcopy(self)

    @staticmethod
    def _array_index(part, length, allow_dash=False):
        if part == '-':
            if allow_dash:
                return length
            raise JsonPatchConflict("invalid array index '-'")
        try:
            if not str(part).isdigit() or (str(part) != '0' and str(part).startswith('0')):
                raise ValueError
            index = int(part)
        except (TypeError, ValueError):
            raise JsonPointerException("invalid array index '{0}'".format(part))
        if index < 0 or (not allow_dash and index >= length):
            raise JsonPatchConflict(
                "array index '{0}' is out of bounds".format(part))
        if allow_dash and index > length:
            raise JsonPatchConflict("can't insert outside of list")
        return index

    def _resolve_parent(self, parts, allow_dash=False):
        node = self.root
        raw = node.raw
        for part in parts[:-1]:
            if isinstance(node.raw, MutableMapping):
                if part not in node.children:
                    return None, part, node, raw
                node = node.children[part]
                raw = node.raw
            elif isinstance(node.raw, MutableSequence):
                index = self._array_index(part, len(node.children))
                node = node.children[index]
                raw = node.raw[index]
            else:
                return None, part, node, raw
        if not parts:
            return node, None, None, self.root.raw
        last = parts[-1]
        if isinstance(node.raw, MutableMapping):
            child = node.children.get(last)
            return child, last, node, node.raw
        if isinstance(node.raw, MutableSequence):
            index = self._array_index(
                last, len(node.children), allow_dash=allow_dash)
            child = node.children[index] if index < len(node.children) else None
            return child, index, node, node.raw
        return None, last, node, node.raw

    def resolve(self, pointer, allow_dash=False):
        if not pointer.parts:
            return self.root, None, None, self.root.raw
        return self._resolve_parent(pointer.parts, allow_dash=allow_dash)

    def try_resolve(self, pointer, allow_dash=False):
        try:
            return self.resolve(pointer, allow_dash=allow_dash)
        except (JsonPatchConflict, JsonPointerException, IndexError, KeyError):
            return None, None, None, None

    def _attach(self, parent, key, node):
        node.parent = parent
        node.key = key
        if parent is None:
            self.root = node
            self._index_subtree(node)
            return
        if isinstance(parent.raw, MutableMapping):
            parent.children[key] = node
            parent.raw[key] = node.raw
        else:
            parent.children.insert(key, node)
            parent.raw.insert(key, node.raw)
            for index, child in enumerate(parent.children):
                child.key = index
        self._index_subtree(node)

    def _detach(self, parent, key):
        if parent is None:
            node = self.root
            self.root = None
            self._unindex_subtree(node)
            return node
        if isinstance(parent.raw, MutableMapping):
            node = parent.children.pop(key)
            del parent.raw[key]
        else:
            node = parent.children.pop(key)
            parent.raw.pop(key)
            for index, child in enumerate(parent.children):
                child.key = index
        node.parent = None
        node.key = None
        self._unindex_subtree(node)
        return node

    @staticmethod
    def _mark_subtree(node, changed_by=None, moved_by=None):
        stack = [node]
        while stack:
            current = stack.pop()
            if changed_by is not None:
                current.changed_by.update(changed_by)
            if moved_by is not None:
                current.moved_by.update(moved_by)
            if isinstance(current.raw, MutableMapping):
                stack.extend(current.children.values())
            elif isinstance(current.raw, MutableSequence):
                stack.extend(current.children)

    def _tombstone(self, node, by=None, reason=''):
        if node is None:
            return
        if by is not None:
            node.tombstoned_by.update(by)
        node.tombstone_reason = reason
        self.tombstones[node.id] = node
        if isinstance(node.raw, MutableMapping):
            for child in node.children.values():
                self._tombstone(child, by=by, reason='ancestor_' + reason if reason else '')
        elif isinstance(node.raw, MutableSequence):
            for child in node.children:
                self._tombstone(child, by=by, reason='ancestor_' + reason if reason else '')

    def add(self, pointer, value, node_id, operation_marker):
        child, key, parent, _ = self.resolve(pointer, allow_dash=True)
        node = self._build(copy.deepcopy(value), node_id, None, None)
        if parent is None:
            if self.root is not None:
                self._tombstone(self.root, by={operation_marker}, reason='replace')
                self._detach(None, None)
            self._attach(None, None, node)
        else:
            if child is not None and isinstance(parent.raw, MutableMapping):
                self._tombstone(child, by={operation_marker}, reason='replace')
                self._detach(parent, key)
            self._attach(parent, key, node)
        self._mark_subtree(node, changed_by=(operation_marker,))
        return node

    def remove(self, pointer, operation_marker):
        child, _, parent, _ = self.resolve(pointer)
        self._tombstone(child, by={operation_marker}, reason='remove')
        return self._detach(parent, child.key)

    def replace(self, pointer, value, node_id, operation_marker):
        child, _, parent, _ = self.resolve(pointer)
        key = child.key
        changed_by = set(child.changed_by)
        changed_by.add(operation_marker)
        node = self._build(
            copy.deepcopy(value), node_id, None, None,
            changed_by=changed_by, moved_by=child.moved_by)
        if parent is None:
            self._tombstone(child, by={operation_marker}, reason='replace')
            self._detach(None, None)
            self._attach(None, None, node)
        else:
            self._tombstone(child, by={operation_marker}, reason='replace')
            self._detach(parent, key)
            self._attach(parent, key, node)
        return node

    def move(self, from_pointer, path_pointer, operation_index,
             destination_index=None):
        source, _, source_parent, _ = self.resolve(from_pointer)
        if source_parent is None:
            raise JsonPatchConflict("can't move root document")
        key = source.key
        _, _, destination_parent_pre, _ = self._resolve_parent(
            path_pointer.parts[:-1])
        same_sequence = isinstance(source_parent.raw, MutableSequence) and \
            len(path_pointer.parts) >= 2 and \
            destination_parent_pre is source_parent
        if same_sequence:
            if path_pointer.parts[-1] == '-':
                destination_index = len(source_parent.children)
            else:
                requested_index = self._array_index(
                    path_pointer.parts[-1],
                    len(source_parent.children) + 1,
                    allow_dash=True)
                destination_index = requested_index - 1 if \
                    requested_index > key else requested_index
        node = self._detach(source_parent, key)
        if same_sequence:
            self._attach(source_parent, destination_index, node)
            node.direct_moved_by.add(operation_index)
            self._mark_subtree(node, moved_by=(operation_index,))
            return node
        destination_child, destination_key, destination_parent, _ = \
            self.resolve(path_pointer, allow_dash=True)
        if destination_parent is not None and isinstance(
                destination_parent.raw, MutableMapping) and \
                destination_child is not None:
            self._tombstone(destination_child, by={operation_index},
                            reason='destination_replaced')
            self._detach(destination_parent, destination_key)
        self._attach(destination_parent, destination_key, node)
        node.direct_moved_by.add(operation_index)
        self._mark_subtree(node, moved_by=(operation_index,))
        return node

    def copy_node(self, from_pointer, path_pointer, id_factory,
                  operation_marker, destination_index=None):
        source, _, _, _ = self.resolve(from_pointer)
        destination_child, destination_key, destination_parent, _ = \
            self.resolve(path_pointer, allow_dash=True)

        def clone(node, suffix):
            new_id = id_factory(suffix)
            new_node = node._clone(new_id=new_id, moved_by=())
            new_node.tombstoned_by = set()
            new_node.tombstone_reason = ''
            new_node.direct_moved_by = set()
            if isinstance(node.raw, MutableMapping):
                new_node.raw = type(node.raw)()
                new_node.children = {}
                for child_key, child in node.children.items():
                    new_child = clone(child, suffix + ('dict', child_key))
                    self._attach(new_node, child_key, new_child)
            elif isinstance(node.raw, MutableSequence):
                new_node.raw = type(node.raw)()
                new_node.children = []
                for index, child in enumerate(node.children):
                    new_child = clone(child, suffix + ('list', index))
                    self._attach(new_node, index, new_child)
            else:
                new_node.tombstoned_by = set()
                new_node.tombstone_reason = ''
                new_node.direct_moved_by = set()
            return new_node

        suffix = ()
        root_suffix = ()
        new_node = clone(source, root_suffix)
        if destination_parent is not None and isinstance(
                destination_parent.raw, MutableMapping) and \
                destination_child is not None:
            self._tombstone(destination_child, by={operation_marker},
                            reason='destination_replaced')
            self._detach(destination_parent, destination_key)
        self._attach(destination_parent, destination_key, new_node)
        self._mark_subtree(new_node, changed_by=(operation_marker,))
        return new_node

    @staticmethod
    def raw_value(node):
        if node is None:
            return None
        return copy.deepcopy(node.raw)


class _Rebaser(object):
    def __init__(self, base, applied, pending):
        self.base = copy.deepcopy(base)
        self.applied_ops = self._as_ops(applied)
        self.pending_ops = self._as_ops(pending)
        self.target = _IdentityState(self.base, ('base',))
        self.source = _IdentityState(self.base, ('base',))
        self.result = []
        self.conflicts = []

    @staticmethod
    def _as_ops(patch):
        if isinstance(patch, JsonPatch):
            return copy.deepcopy(patch.patch)
        if isinstance(patch, basestring):
            return JsonPatch.from_string(patch).patch
        return copy.deepcopy(list(patch))

    def run(self):
        for index, op_data in enumerate(self.applied_ops):
            self._apply_applied(index, op_data)

        for index, op_data in enumerate(self.pending_ops):
            operation = JsonPatch([op_data])._get_operation(copy.deepcopy(op_data))
            source_state = self.source
            target_state = self.target
            self.source = source_state.snapshot()
            self.target = target_state.snapshot()
            conflict_count = len(self.conflicts)
            transformed = self._rebase_operation(index, operation, op_data)
            if len(self.conflicts) != conflict_count:
                self.source = source_state
                self.target = target_state
            if len(self.conflicts) == conflict_count and transformed is not None:
                self.result.append(transformed)

        return RebaseResult(self.result, self.conflicts)

    @staticmethod
    def _pointer(operation, attribute='path'):
        value = operation.operation[attribute]
        if isinstance(value, JsonPointer):
            return value
        return JsonPointer(value)

    @staticmethod
    def _escape_part(part):
        return str(part).replace('~', '~0').replace('/', '~1')

    def _path_for_node(self, node):
        if node is None or node.parent is None:
            return ''
        parts = []
        current = node
        while current.parent is not None:
            parts.append(self._escape_part(current.key))
            current = current.parent
        return ''.join('/' + part for part in reversed(parts))

    @staticmethod
    def _same_json(left, right):
        return json.dumps(left, sort_keys=True) == \
            json.dumps(right, sort_keys=True)

    @staticmethod
    def _applied_indexes(*nodes):
        indexes = set()
        for node in nodes:
            if node is None:
                continue
            for marker in node.changed_by | node.moved_by:
                if isinstance(marker, tuple) and \
                        len(marker) >= 2 and marker[0] == 'applied':
                    indexes.add(marker[1])
            for marker in node.tombstoned_by:
                if isinstance(marker, tuple) and \
                        len(marker) >= 2 and marker[0] == 'applied':
                    indexes.add(marker[1])
        return sorted(indexes)

    def _conflict(self, index, op_data, reason, path, from_path=None,
                  related=None):
        conflict = RebaseConflict(
            index, path, reason, op_data, from_path=from_path,
            applied_operation_indexes=self._applied_indexes(
                *(related or ())))
        self.conflicts.append(conflict)

    def _new_id(self, kind, index, path):
        self.source.next_id += 1
        return ('pending', kind, index, path, self.source.next_id)

    def _copy_id_factory(self, index, path, kind='pending'):
        def factory(suffix):
            return (kind, 'copy', index, path) + suffix
        return factory

    def _apply_applied(self, index, op_data):
        marker = ('applied', index)
        op_type = op_data['op']
        path = self._pointer(
            JsonPatch([op_data])._get_operation(copy.deepcopy(op_data)))
        if op_type == 'add':
            self.target.add(
                path, op_data.get('value'),
                ('applied', 'add', index, path.path), marker)
        elif op_type == 'replace':
            self.target.replace(
                path, op_data.get('value'),
                ('applied', 'replace', index, path.path), marker)
        elif op_type == 'remove':
            self.target.remove(path, marker)
        elif op_type == 'move':
            from_pointer = JsonPointer(op_data['from'])
            self.target.move(from_pointer, path, marker)
        elif op_type == 'copy':
            from_pointer = JsonPointer(op_data['from'])
            self.target.copy_node(
                from_pointer, path,
                self._copy_id_factory(index, path.path, kind='applied'),
                marker)

    def _array_insert_index(self, state, source_parent, source_parts,
                            source_child, skip_id=None):
        if not source_parts:
            return 0
        if source_parts[-1] == '-':
            target_parent = state.find_id(source_parent.id)
            return len(target_parent.children)
        original_index = int(source_parts[-1])
        successor_index = original_index
        if source_child is None and original_index < len(source_parent.children):
            successor_index += 1
        for source_node in source_parent.children[successor_index:]:
            if skip_id is not None and source_node.id == skip_id:
                continue
            target_node = state.find_id(source_node.id)
            if target_node is not None and \
                    target_node.parent is not None and \
                    target_node.parent.id == source_parent.id:
                previous = target_node.parent.children[target_node.key - 1] \
                    if target_node.key else None
                return target_node.key
        target_parent = state.find_id(source_parent.id)
        return len(target_parent.children)

    @staticmethod
    def _is_inside(ancestor, node):
        current = node
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False

    @staticmethod
    def _subtree_has_applied_change(node, root_id_prefix=('base',)):
        if node is None:
            return False
        stack = [node]
        while stack:
            current = stack.pop()
            if current.changed_by:
                return True
            if isinstance(current.id, tuple) and \
                    len(current.id) >= 2 and current.id[0] == 'applied':
                return True
            if isinstance(current.raw, MutableMapping):
                stack.extend(current.children.values())
            elif isinstance(current.raw, MutableSequence):
                stack.extend(current.children)
        return False

    def _rebase_operation(self, index, operation, op_data):
        name = operation.operation['op']
        handler = getattr(self, '_rebase_' + name, None)
        if handler is None:
            raise InvalidJsonPatch("Unknown operation {0!r}".format(name))
        return handler(index, operation, op_data)

    def _rebase_test(self, index, operation, op_data):
        pointer = self._pointer(operation)
        source_node, _, _, _ = self.source.resolve(
            pointer, allow_dash=True)
        target_node, _, target_parent, _ = self.target.try_resolve(
            pointer, allow_dash=True)
        source_value = self.source.raw_value(source_node)
        target_value = self.target.raw_value(target_node)
        if not self._same_json(source_value, op_data['value']):
            raise JsonPatchTestFailed(
                'test operation was not valid in pending document')
        if (target_parent is None and pointer.parts) or \
                not self._same_json(target_value, op_data['value']):
            self._conflict(index, op_data, 'test_precondition_failed',
                           pointer.path, related=(source_node, target_node))
            return None
        transformed = copy.deepcopy(op_data)
        return transformed

    def _resolve_both(self, operation, from_attribute=None, allow_dash=False):
        path_pointer = self._pointer(operation)
        source = self.source.resolve(path_pointer, allow_dash=allow_dash)
        target = self._identity_resolve(
            self.target, path_pointer, source, allow_dash=allow_dash)
        from_source = from_target = from_pointer = None
        if from_attribute is not None:
            from_pointer = self._pointer(operation, from_attribute)
            from_source = self.source.resolve(from_pointer)
            from_target = self._identity_resolve(
                self.target, from_pointer, from_source)
        return (path_pointer, source, target, from_pointer,
                from_source, from_target)

    def _identity_resolve(self, state, pointer, source_resolution=None,
                          allow_dash=False):
        try:
            return state.resolve(pointer, allow_dash=allow_dash)
        except (JsonPatchConflict, JsonPointerException, IndexError,
                KeyError):
            if source_resolution is None or not pointer.parts:
                return None, None, None, None
            source_child = source_resolution[0]
            if source_child is not None:
                target_node = state.find_id(source_child.id)
                if target_node is not None and target_node.parent is not None:
                    return (target_node, target_node.key,
                            target_node.parent, target_node.raw)
            effective_parent = self._effective_parent(
                state, source_resolution[2])
            if effective_parent is None:
                return None, None, None, None
            return None, None, effective_parent, effective_parent.raw

    def _effective_parent(self, state, source_parent):
        if source_parent is None:
            return state.root
        if source_parent.parent is None:
            return state.root
        parent = state.find_id(source_parent.id)
        return parent if parent is not None and parent.parent is not None \
            else None

    def _rebase_add(self, index, operation, op_data):
        path_pointer, (source_child, _, source_parent, _), \
            (target_child, _, target_parent, _), _, _, _ = \
            self._resolve_both(operation, allow_dash=True)
        root_operation = not path_pointer.parts
        if root_operation:
            if self.target.root is not None and \
                    self.target.root.id != ('base',):
                self._conflict(index, op_data, 'root_replaced', '',
                               related=(self.target.root,))
                return None
            transformed_path = ''
            node_id = self._new_id('add', index, '')
            self.source.add(path_pointer, op_data['value'], node_id,
                            ('pending', index))
            self.target.add(path_pointer, op_data['value'], node_id,
                            ('pending', index))
            transformed = copy.deepcopy(op_data)
            transformed['path'] = ''
            return transformed

        if source_parent is None or target_parent is None:
            self._conflict(index, op_data, 'ancestor_removed',
                           path_pointer.path, related=(target_parent,))
            return None

        effective_target_parent = self.target.find_id(source_parent.id)
        if effective_target_parent is None or \
                (effective_target_parent.parent is None and
                 effective_target_parent is not self.target.root):
            self._conflict(index, op_data, 'ancestor_removed',
                           path_pointer.path, related=(target_parent,))
            return None

        if isinstance(effective_target_parent.raw, MutableMapping):
            target_child = effective_target_parent.children.get(
                path_pointer.parts[-1])
            if target_child is not None:
                if source_child is None:
                    self._conflict(index, op_data, 'object_key_added',
                                   path_pointer.path,
                                   related=(target_child,))
                    return None
                if target_child.id != source_child.id:
                    self._conflict(index, op_data, 'object_key_replaced',
                                   path_pointer.path,
                                   related=(source_child, target_child))
                    return None
            if source_child is not None and target_child is None:
                self._conflict(index, op_data, 'object_key_removed',
                               path_pointer.path,
                               related=(source_child,))
                return None
            transformed_path = self._join_path(
                self._path_for_node(effective_target_parent),
                path_pointer.parts[-1])
        else:
            transformed_path = self._path_for_node(effective_target_parent)
            if transformed_path:
                transformed_path += '/'
            insert_index = self._array_insert_index(
                self.target, source_parent, path_pointer.parts, source_child)
            transformed_path += str(insert_index)

        node_id = self._new_id('add', index, path_pointer.path)
        self.source.add(path_pointer, op_data['value'], node_id,
                        ('pending', index))
        self.target.add(JsonPointer(transformed_path), op_data['value'],
                        node_id, ('pending', index))
        transformed = copy.deepcopy(op_data)
        transformed['path'] = transformed_path
        return transformed

    def _direct_applied_modification(self, node):
        return node is not None and (
            any(isinstance(marker, tuple) and marker[0] == 'applied'
                for marker in node.changed_by) or
            any(isinstance(marker, tuple) and marker[0] == 'applied'
                for marker in node.moved_by))

    @staticmethod
    def _direct_applied_move(node):
        return node is not None and any(
            isinstance(marker, tuple) and marker[0] == 'applied'
            for marker in node.direct_moved_by)

    def _rebase_replace(self, index, operation, op_data):
        path_pointer, (source_child, _, source_parent, _), \
            (path_child, _, target_parent, _), _, _, _ = \
            self._resolve_both(operation)
        if source_parent is None and target_parent is None:
            if self.target.root.changed_by or self.target.root.moved_by or \
                    not self._same_json(self.source.root.raw, self.target.root.raw):
                self._conflict(index, op_data, 'root_replaced', '',
                               related=(self.source.root, self.target.root))
                return None
            transformed_path = ''
            node_id = self._new_id('replace', index, '')
            self.source.replace(path_pointer, op_data['value'], node_id,
                                ('pending', index))
            self.target.replace(path_pointer, op_data['value'], node_id,
                                ('pending', index))
            transformed = copy.deepcopy(op_data)
            transformed['path'] = transformed_path
            return transformed

        if source_child is None:
            self._conflict(index, op_data, 'target_removed',
                           path_pointer.path,
                           related=None)
            return None

        if path_child is None or path_child.id != source_child.id:
            target_node = self.target.find_id(source_child.id)
            if target_node is None or target_node.parent is None:
                tombstone = self.target.tombstones.get(source_child.id)
                if tombstone is None:
                    reason = 'target_moved'
                elif tombstone.tombstone_reason == 'replace':
                    reason = 'same_scalar_modified'
                elif tombstone.tombstone_reason.startswith('ancestor_'):
                    reason = 'ancestor_removed'
                else:
                    reason = 'target_removed'
                self._conflict(index, op_data, reason,
                               path_pointer.path,
                               related=(source_child, tombstone))
                return None
            if self._direct_applied_move(target_node):
                self._conflict(index, op_data, 'target_moved',
                               path_pointer.path,
                               related=(source_child, target_node))
                return None
            if self._same_json(source_child.raw, target_node.raw):
                transformed_parent = self._path_for_node(target_node.parent)
                if isinstance(target_node.parent.raw, MutableMapping):
                    transformed_path = self._join_path(
                        transformed_parent, target_node.key)
                else:
                    transformed_path = self._join_path(
                        transformed_parent, target_node.key)
            else:
                self._conflict(index, op_data, 'same_scalar_modified',
                               path_pointer.path,
                               related=(source_child, target_node))
                return None
        else:
            target_node = path_child
            if not self._same_json(source_child.raw, target_node.raw):
                self._conflict(index, op_data, 'same_scalar_modified',
                               path_pointer.path,
                               related=(source_child, target_node))
                return None
            transformed_path = self._path_for_node(target_node)

        node_id = self._new_id('replace', index, path_pointer.path)
        self.source.replace(path_pointer, op_data['value'], node_id,
                            ('pending', index))
        self.target.replace(JsonPointer(transformed_path), op_data['value'],
                            node_id, ('pending', index))
        transformed = copy.deepcopy(op_data)
        transformed['path'] = transformed_path
        return transformed

    @staticmethod
    def _join_path(path, key):
        if not path:
            return '/' + str(key).replace('~', '~0').replace('/', '~1')
        return path + '/' + str(key).replace('~', '~0').replace('/', '~1')

    def _subtree_applied_changes(self, node):
        if node is None:
            return False
        stack = [node]
        while stack:
            current = stack.pop()
            if any(isinstance(marker, tuple) and marker[0] == 'applied'
                   for marker in current.changed_by):
                return True
            if isinstance(current.id, tuple) and current.id[0] == 'applied':
                return True
            if isinstance(current.raw, MutableMapping):
                stack.extend(current.children.values())
            elif isinstance(current.raw, MutableSequence):
                stack.extend(current.children)
        return False

    def _rebase_remove(self, index, operation, op_data):
        path_pointer, (source_child, _, source_parent, _), \
            (path_child, _, target_parent, _), _, _, _ = \
            self._resolve_both(operation)
        if source_child is None:
            return None
        if source_parent is None:
            if self.target.root.changed_by or self.target.root.moved_by or \
                    self._subtree_applied_changes(self.target.root):
                self._conflict(index, op_data, 'root_modified', '',
                               related=(self.source.root, self.target.root))
                return None
            self._conflict(index, op_data, 'root_remove_unsupported', '')
            return None

        target_node = self.target.find_id(source_child.id)
        if target_node is None or target_node.parent is None:
            tombstone = self.target.tombstones.get(source_child.id)
            if tombstone is not None and \
                    (tombstone.tombstone_reason == 'remove' or
                     tombstone.tombstone_reason.startswith('ancestor_')):
                return None
            if tombstone is not None and \
                    tombstone.tombstone_reason == 'replace':
                self._conflict(index, op_data, 'same_scalar_modified',
                               path_pointer.path,
                               related=(source_child, tombstone))
                return None
            self._conflict(index, op_data, 'target_removed',
                           path_pointer.path,
                           related=(source_child, tombstone))
            return None

        if path_child is not None and path_child.id == source_child.id:
            if self._subtree_applied_changes(target_node):
                self._conflict(index, op_data, 'ancestor_removed',
                               path_pointer.path,
                               related=(source_child, target_node))
                return None
            transformed_path = self._path_for_node(target_node)
        else:
            if self._direct_applied_move(target_node):
                self._conflict(index, op_data, 'target_moved',
                               path_pointer.path,
                               related=(source_child, target_node))
                return None
            transformed_path = self._path_for_node(target_node)

        self.source.remove(path_pointer, ('pending', index))
        self.target.remove(JsonPointer(transformed_path), ('pending', index))
        transformed = copy.deepcopy(op_data)
        transformed['path'] = transformed_path
        return transformed

    def _array_destination_index(self, source_parent, source_parts,
                                 source_from_child, operation_type):
        target_parent = self.target.find_id(source_parent.id)
        if target_parent is None:
            return None
        if not isinstance(target_parent.raw, MutableSequence):
            return target_parent.key
        if source_parts[-1] == '-':
            return len(target_parent.children)
        original_index = int(source_parts[-1])
        start = original_index
        if operation_type == 'move' and source_from_child is not None and \
                source_from_child.parent is not None and \
                source_from_child.parent.id == source_parent.id:
            source_from_current = self.source.find_id(source_from_child.id)
            if source_from_current is not None and \
                    source_from_current.parent is not None and \
                    source_from_current.parent.id == source_parent.id and \
                    source_from_current.key < start:
                start -= 1
        for source_node in source_parent.children[start:]:
            if source_from_child is not None and \
                    source_node.id == source_from_child.id:
                continue
            target_node = self.target.find_id(source_node.id)
            if target_node is not None and target_node.parent is not None and \
                    target_node.parent.id == source_parent.id:
                return target_node.key
        return len(target_parent.children)

    def _rebase_move(self, index, operation, op_data):
        path_pointer, (source_destination, _, source_destination_parent, _), \
            (target_destination, _, target_destination_parent, _), \
            from_pointer, (source_from, _, source_from_parent, _), \
            (target_from, _, target_from_parent, _) = self._resolve_both(
                operation, from_attribute='from', allow_dash=True)

        if path_pointer.contains(from_pointer) and path_pointer != from_pointer:
            raise InvalidJsonPatch('Cannot move values into their own children')
        if source_from is None or source_from_parent is None:
            tombstone = self.target.tombstones.get(
                getattr(source_from, 'id', None))
            self._conflict(index, op_data, 'move_source_removed',
                           from_pointer.path, from_path=from_pointer.path,
                           related=(tombstone,))
            return None
        source_from_target = self.target.find_id(source_from.id)
        if source_from_target is None or source_from_target.parent is None:
            tombstone = self.target.tombstones.get(source_from.id)
            reason = 'move_source_modified' if tombstone is not None and \
                tombstone.tombstone_reason == 'replace' else \
                'move_source_removed'
            self._conflict(index, op_data, reason,
                           from_pointer.path, from_path=from_pointer.path,
                           related=(source_from, tombstone))
            return None
        if self._direct_applied_move(source_from_target):
            transformed_from = self._path_for_node(source_from_target)
            effective_parent = self.target.find_id(
                source_destination_parent.id) if \
                source_destination_parent is not None else None
            if isinstance(source_destination_parent.raw, MutableMapping):
                transformed_path = self._join_path(
                    self._path_for_node(effective_parent),
                    path_pointer.parts[-1])
            else:
                transformed_path = self._join_path(
                    self._path_for_node(effective_parent),
                    self._array_destination_index(
                        source_destination_parent, path_pointer.parts,
                        source_from, 'move'))
            if transformed_from == from_pointer.path and \
                    transformed_path == path_pointer.path:
                return None
            self._conflict(index, op_data, 'move_source_moved',
                           path_pointer.path, from_path=from_pointer.path,
                           related=(source_from, source_from_target))
            return None
        if source_destination_parent is None or \
                target_destination_parent is None:
            self._conflict(index, op_data, 'move_destination_removed',
                           path_pointer.path,
                           from_path=from_pointer.path,
                           related=(source_destination_parent,
                                    target_destination_parent))
            return None

        if isinstance(source_destination_parent.raw, MutableMapping):
            if source_destination is not None and \
                    source_destination.id == source_from.id and \
                    from_pointer.path == path_pointer.path:
                return None
            if target_destination is not None:
                if source_destination is None:
                    self._conflict(index, op_data, 'move_destination_added',
                                   path_pointer.path,
                                   from_path=from_pointer.path,
                                   related=(target_destination,))
                    return None
                if target_destination.id != source_destination.id or \
                        not self._same_json(
                            source_destination.raw, target_destination.raw):
                    self._conflict(index, op_data,
                                   'move_destination_modified',
                                   path_pointer.path,
                                   from_path=from_pointer.path,
                                   related=(source_destination,
                                            target_destination))
                    return None
            elif source_destination is not None:
                self._conflict(index, op_data, 'move_destination_removed',
                               path_pointer.path,
                               from_path=from_pointer.path,
                               related=(source_destination,))
                return None

        transformed_from = self._path_for_node(source_from_target)
        if isinstance(source_destination_parent.raw, MutableMapping):
            effective_destination_parent = self.target.find_id(
                source_destination_parent.id)
            transformed_path = self._path_for_node(effective_destination_parent)
            transformed_path = self._join_path(
                transformed_path, path_pointer.parts[-1])
        else:
            target_parent_path = self._path_for_node(
                self.target.find_id(source_destination_parent.id))
            if source_destination_parent.id == source_from_parent.id and \
                    path_pointer.parts[-1] == '-':
                transformed_path = target_parent_path + '/-'
            else:
                insert_index = self._array_destination_index(
                    source_destination_parent, path_pointer.parts,
                    source_from, 'move')
                transformed_path = self._join_path(
                    target_parent_path, insert_index)

        self.source.move(from_pointer, path_pointer, ('pending', index))
        self.target.move(
            JsonPointer(transformed_from), JsonPointer(transformed_path),
            ('pending', index))
        transformed = copy.deepcopy(op_data)
        transformed['from'] = transformed_from
        transformed['path'] = transformed_path
        return transformed

    def _rebase_copy(self, index, operation, op_data):
        path_pointer, (source_destination, _, source_destination_parent, _), \
            (target_destination, _, target_destination_parent, _), \
            from_pointer, (source_from, _, source_from_parent, _), \
            _ = self._resolve_both(
                operation, from_attribute='from', allow_dash=True)
        if source_from is None or source_from_parent is None:
            self._conflict(index, op_data, 'copy_source_removed',
                           from_pointer.path, from_path=from_pointer.path)
            return None
        source_from_target = self.target.find_id(source_from.id)
        if source_from_target is None or source_from_target.parent is None:
            self._conflict(index, op_data, 'copy_source_removed',
                           from_pointer.path, from_path=from_pointer.path,
                           related=(source_from,))
            return None
        if source_destination_parent is None or \
                target_destination_parent is None:
            self._conflict(index, op_data, 'copy_destination_removed',
                           path_pointer.path,
                           from_path=from_pointer.path)
            return None
        if isinstance(source_destination_parent.raw, MutableMapping):
            if target_destination is not None:
                if source_destination is None:
                    self._conflict(index, op_data, 'copy_destination_added',
                                   path_pointer.path,
                                   from_path=from_pointer.path,
                                   related=(target_destination,))
                    return None
                if target_destination.id != source_destination.id or \
                        not self._same_json(
                            source_destination.raw, target_destination.raw):
                    self._conflict(index, op_data,
                                   'copy_destination_modified',
                                   path_pointer.path,
                                   from_path=from_pointer.path,
                                   related=(source_destination,
                                            target_destination))
                    return None
            elif source_destination is not None:
                self._conflict(index, op_data, 'copy_destination_removed',
                               path_pointer.path,
                               from_path=from_pointer.path,
                               related=(source_destination,))
                return None
            transformed_path = self._join_path(
                self._path_for_node(self.target.find_id(
                    source_destination_parent.id)),
                path_pointer.parts[-1])
        else:
            target_parent_path = self._path_for_node(
                self.target.find_id(source_destination_parent.id))
            insert_index = self._array_destination_index(
                source_destination_parent, path_pointer.parts, None, 'copy')
            transformed_path = self._join_path(
                target_parent_path, insert_index)

        transformed_from = self._path_for_node(source_from_target)
        pending_id_path = from_pointer.path + '->' + path_pointer.path
        factory = self._copy_id_factory(index, pending_id_path, kind='pending')
        self.source.copy_node(
            from_pointer, path_pointer, factory, ('pending', index))
        self.target.copy_node(
            JsonPointer(transformed_from), JsonPointer(transformed_path),
            factory, ('pending', index))
        transformed = copy.deepcopy(op_data)
        transformed['from'] = transformed_from
        transformed['path'] = transformed_path
        return transformed
