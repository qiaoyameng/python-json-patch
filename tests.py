#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import json
import decimal
import doctest
import copy
import random
import unittest
import jsonpatch
import jsonpointer
import sys
try:
    from types import MappingProxyType
except ImportError:
    # Python < 3.3
    MappingProxyType = dict


class ApplyPatchTestCase(unittest.TestCase):

    def test_js_file(self):
        with open('./tests.js', 'r') as f:
            tests = json.load(f)
            for test in tests:
                try:
                    if 'expected' not in test:
                        continue
                    result = jsonpatch.apply_patch(test['doc'], test['patch'])
                    self.assertEqual(result, test['expected'])
                except Exception:
                    if test.get('error'):
                        continue
                    else:
                        raise

    def test_success_if_replaced_dict(self):
        src = [{'a': 1}, {'b': 2}]
        dst = [{'a': 1, 'b': 2}]
        patch = jsonpatch.make_patch(src, dst)
        self.assertEqual(patch.apply(src), dst)

    def test_success_if_raise_no_error(self):
        src = [{}]
        dst = [{'key': ''}]
        patch = jsonpatch.make_patch(src, dst)
        patch.apply(src)
        self.assertTrue(True)

    def test_apply_patch_from_string(self):
        obj = {'foo': 'bar'}
        patch = '[{"op": "add", "path": "/baz", "value": "qux"}]'
        res = jsonpatch.apply_patch(obj, patch)
        self.assertTrue(obj is not res)
        self.assertTrue('baz' in res)
        self.assertEqual(res['baz'], 'qux')

    def test_apply_patch_to_copy(self):
        obj = {'foo': 'bar'}
        res = jsonpatch.apply_patch(obj, [{'op': 'add', 'path': '/baz', 'value': 'qux'}])
        self.assertTrue(obj is not res)

    def test_apply_patch_to_same_instance(self):
        obj = {'foo': 'bar'}
        res = jsonpatch.apply_patch(obj, [{'op': 'add', 'path': '/baz', 'value': 'qux'}],
                                    in_place=True)
        self.assertTrue(obj is res)

    def test_add_object_key(self):
        obj = {'foo': 'bar'}
        res = jsonpatch.apply_patch(obj, [{'op': 'add', 'path': '/baz', 'value': 'qux'}])
        self.assertTrue('baz' in res)
        self.assertEqual(res['baz'], 'qux')

    def test_add_array_item(self):
        obj = {'foo': ['bar', 'baz']}
        res = jsonpatch.apply_patch(obj, [{'op': 'add', 'path': '/foo/1', 'value': 'qux'}])
        self.assertEqual(res['foo'], ['bar', 'qux', 'baz'])

    def test_remove_object_key(self):
        obj = {'foo': 'bar', 'baz': 'qux'}
        res = jsonpatch.apply_patch(obj, [{'op': 'remove', 'path': '/baz'}])
        self.assertTrue('baz' not in res)

    def test_remove_array_item(self):
        obj = {'foo': ['bar', 'qux', 'baz']}
        res = jsonpatch.apply_patch(obj, [{'op': 'remove', 'path': '/foo/1'}])
        self.assertEqual(res['foo'], ['bar', 'baz'])

    def test_remove_invalid_item(self):
        obj = {'foo': ['bar', 'qux', 'baz']}
        with self.assertRaises(jsonpointer.JsonPointerException):
            jsonpatch.apply_patch(obj, [{'op': 'remove', 'path': '/foo/-'}])


    def test_replace_object_key(self):
        obj = {'foo': 'bar', 'baz': 'qux'}
        res = jsonpatch.apply_patch(obj, [{'op': 'replace', 'path': '/baz', 'value': 'boo'}])
        self.assertTrue(res['baz'], 'boo')

    def test_replace_whole_document(self):
        obj = {'foo': 'bar'}
        res = jsonpatch.apply_patch(obj, [{'op': 'replace', 'path': '', 'value': {'baz': 'qux'}}])
        self.assertTrue(res['baz'], 'qux')

    def test_add_replace_whole_document(self):
        obj = {'foo': 'bar'}
        new_obj = {'baz': 'qux'}
        res = jsonpatch.apply_patch(obj, [{'op': 'add', 'path': '', 'value': new_obj}])
        self.assertTrue(res, new_obj)

    def test_replace_array_item(self):
        obj = {'foo': ['bar', 'qux', 'baz']}
        res = jsonpatch.apply_patch(obj, [{'op': 'replace', 'path': '/foo/1',
                                           'value': 'boo'}])
        self.assertEqual(res['foo'], ['bar', 'boo', 'baz'])

    def test_move_object_keyerror(self):
        obj = {'foo': {'bar': 'baz'},
               'qux': {'corge': 'grault'}}
        patch_obj = [ {'op': 'move', 'from': '/foo/non-existent', 'path': '/qux/thud'} ]
        self.assertRaises(jsonpatch.JsonPatchConflict, jsonpatch.apply_patch, obj, patch_obj)

    def test_move_object_key(self):
        obj = {'foo': {'bar': 'baz', 'waldo': 'fred'},
               'qux': {'corge': 'grault'}}
        res = jsonpatch.apply_patch(obj, [{'op': 'move', 'from': '/foo/waldo',
                                           'path': '/qux/thud'}])
        self.assertEqual(res, {'qux': {'thud': 'fred', 'corge': 'grault'},
                               'foo': {'bar': 'baz'}})

    def test_move_array_item(self):
        obj =  {'foo': ['all', 'grass', 'cows', 'eat']}
        res = jsonpatch.apply_patch(obj, [{'op': 'move', 'from': '/foo/1', 'path': '/foo/3'}])
        self.assertEqual(res, {'foo': ['all', 'cows', 'eat', 'grass']})

    def test_move_array_item_into_other_item(self):
        obj = [{"foo": []}, {"bar": []}]
        patch = [{"op": "move", "from": "/0", "path": "/0/bar/0"}]
        res = jsonpatch.apply_patch(obj, patch)
        self.assertEqual(res, [{'bar': [{"foo": []}]}])

    def test_copy_object_keyerror(self):
        obj = {'foo': {'bar': 'baz'},
               'qux': {'corge': 'grault'}}
        patch_obj = [{'op': 'copy', 'from': '/foo/non-existent', 'path': '/qux/thud'}]
        self.assertRaises(jsonpatch.JsonPatchConflict, jsonpatch.apply_patch, obj, patch_obj)

    def test_copy_object_key(self):
        obj = {'foo': {'bar': 'baz', 'waldo': 'fred'},
               'qux': {'corge': 'grault'}}
        res = jsonpatch.apply_patch(obj, [{'op': 'copy', 'from': '/foo/waldo',
                                           'path': '/qux/thud'}])
        self.assertEqual(res, {'qux': {'thud': 'fred', 'corge': 'grault'},
                               'foo': {'bar': 'baz', 'waldo': 'fred'}})

    def test_copy_array_item(self):
        obj =  {'foo': ['all', 'grass', 'cows', 'eat']}
        res = jsonpatch.apply_patch(obj, [{'op': 'copy', 'from': '/foo/1', 'path': '/foo/3'}])
        self.assertEqual(res, {'foo': ['all', 'grass', 'cows', 'grass', 'eat']})


    def test_copy_mutable(self):
        """ test if mutable objects (dicts and lists) are copied by value """
        obj = {'foo': [{'bar': 42}, {'baz': 3.14}], 'boo': []}
        # copy object somewhere
        res = jsonpatch.apply_patch(obj, [{'op': 'copy', 'from': '/foo/0', 'path': '/boo/0' }])
        self.assertEqual(res, {'foo': [{'bar': 42}, {'baz': 3.14}], 'boo': [{'bar': 42}]})
        # modify original object
        res = jsonpatch.apply_patch(res, [{'op': 'add', 'path': '/foo/0/zoo', 'value': 255}])
        # check if that didn't modify the copied object
        self.assertEqual(res['boo'], [{'bar': 42}])


    def test_test_success(self):
        obj =  {'baz': 'qux', 'foo': ['a', 2, 'c']}
        jsonpatch.apply_patch(obj, [{'op': 'test', 'path': '/baz', 'value': 'qux'},
                                    {'op': 'test', 'path': '/foo/1', 'value': 2}])

    def test_test_whole_obj(self):
        obj =  {'baz': 1}
        jsonpatch.apply_patch(obj, [{'op': 'test', 'path': '', 'value': obj}])


    def test_test_error(self):
        obj =  {'bar': 'qux'}
        self.assertRaises(jsonpatch.JsonPatchTestFailed,
                          jsonpatch.apply_patch,
                          obj, [{'op': 'test', 'path': '/bar', 'value': 'bar'}])


    def test_test_not_existing(self):
        obj =  {'bar': 'qux'}
        self.assertRaises(jsonpatch.JsonPatchTestFailed,
                          jsonpatch.apply_patch,
                          obj, [{'op': 'test', 'path': '/baz', 'value': 'bar'}])


    def test_forgetting_surrounding_list(self):
        obj =  {'bar': 'qux'}
        self.assertRaises(jsonpatch.InvalidJsonPatch,
                          jsonpatch.apply_patch,
                          obj, {'op': 'test', 'path': '/bar'})

    def test_test_noval_existing(self):
        obj =  {'bar': 'qux'}
        self.assertRaises(jsonpatch.InvalidJsonPatch,
                          jsonpatch.apply_patch,
                          obj, [{'op': 'test', 'path': '/bar'}])


    def test_test_noval_not_existing(self):
        obj =  {'bar': 'qux'}
        self.assertRaises(jsonpatch.JsonPatchTestFailed,
                          jsonpatch.apply_patch,
                          obj, [{'op': 'test', 'path': '/baz'}])


    def test_test_noval_not_existing_nested(self):
        obj =  {'bar': {'qux': 2}}
        self.assertRaises(jsonpatch.JsonPatchTestFailed,
                          jsonpatch.apply_patch,
                          obj, [{'op': 'test', 'path': '/baz/qx'}])


    def test_unrecognized_element(self):
        obj = {'foo': 'bar', 'baz': 'qux'}
        res = jsonpatch.apply_patch(obj, [{'op': 'replace', 'path': '/baz', 'value': 'boo', 'foo': 'ignore'}])
        self.assertTrue(res['baz'], 'boo')


    def test_append(self):
        obj = {'foo': [1, 2]}
        res = jsonpatch.apply_patch(obj, [
                {'op': 'add', 'path': '/foo/-', 'value': 3},
                {'op': 'add', 'path': '/foo/-', 'value': 4},
            ])
        self.assertEqual(res['foo'], [1, 2, 3, 4])

    def test_add_missing_path(self):
        obj = {'bar': 'qux'}
        self.assertRaises(jsonpatch.InvalidJsonPatch,
                          jsonpatch.apply_patch,
                          obj, [{'op': 'test', 'value': 'bar'}])

    def test_path_with_null_value(self):
        obj = {'bar': 'qux'}
        self.assertRaises(jsonpatch.InvalidJsonPatch,
                          jsonpatch.apply_patch,
                          obj, '[{"op": "add", "path": null, "value": "bar"}]')


class ApplyWithInverseTestCase(unittest.TestCase):

    def assert_application_roundtrip(self, doc, patch):
        original = copy.deepcopy(doc)
        result, inverse = jsonpatch.apply_with_inverse(doc, patch)
        restored = jsonpatch.apply_patch(result, inverse)
        self.assertEqual(restored, original)
        self.assertEqual(doc, original)
        self.assertIsInstance(inverse, list)
        return result, inverse

    def test_returns_plain_patch(self):
        result, inverse = jsonpatch.apply_with_inverse(
            {'foo': 'bar'},
            [{'op': 'add', 'path': '/baz', 'value': 'qux'}]
        )
        self.assertEqual(result, {'foo': 'bar', 'baz': 'qux'})
        self.assertEqual(inverse, [
            {'op': 'remove', 'path': '/baz'}
        ])
        self.assertEqual(jsonpatch.apply_patch(result, inverse), {'foo': 'bar'})

    def test_add_object_member_restores_old_value(self):
        value = {'nested': ['old']}
        result, inverse = jsonpatch.apply_with_inverse(
            {'foo': value},
            [{'op': 'add', 'path': '/foo', 'value': {'nested': ['new']}}]
        )
        self.assertEqual(inverse[0], {
            'op': 'replace',
            'path': '/foo',
            'value': {'nested': ['old']},
        })
        value['nested'].append('changed')
        result['foo']['nested'].append('also changed')
        self.assertEqual(jsonpatch.apply_patch(result, inverse),
                         {'foo': {'nested': ['old']}})

    def test_array_add_remove_and_dash_use_current_indices(self):
        doc = {'items': ['a', 'b', 'c']}
        patch = [
            {'op': 'add', 'path': '/items/-', 'value': 'd'},
            {'op': 'remove', 'path': '/items/0'},
            {'op': 'add', 'path': '/items/1', 'value': 'x'},
            {'op': 'add', 'path': '/items/1', 'value': 'y'},
            {'op': 'remove', 'path': '/items/4'},
        ]
        result, inverse = self.assert_application_roundtrip(doc, patch)
        self.assertEqual(result['items'], ['b', 'y', 'x', 'c'])
        self.assertEqual(inverse, [
            {'op': 'add', 'path': '/items/4', 'value': 'd'},
            {'op': 'remove', 'path': '/items/1'},
            {'op': 'remove', 'path': '/items/1'},
            {'op': 'add', 'path': '/items/0', 'value': 'a'},
            {'op': 'remove', 'path': '/items/3'},
        ])

    def test_move_uses_current_indices_and_target_value(self):
        doc = {'items': ['a', 'b', 'c', 'd'], 'target': 'old'}
        patch = [
            {'op': 'move', 'from': '/items/0', 'path': '/items/3'},
            {'op': 'move', 'from': '/items/2', 'path': '/target'},
        ]
        result, inverse = self.assert_application_roundtrip(doc, patch)
        self.assertEqual(result, {'items': ['b', 'c', 'a'], 'target': 'd'})
        self.assertEqual(inverse, [
            {'op': 'replace', 'path': '/target', 'value': 'old'},
            {'op': 'add', 'path': '/items/2', 'value': 'd'},
            {'op': 'remove', 'path': '/items/3'},
            {'op': 'add', 'path': '/items/0', 'value': 'a'},
        ])

    def test_copy_followed_by_modification(self):
        doc = {'source': {'value': ['original']}}
        patch = [
            {'op': 'copy', 'from': '/source', 'path': '/copy'},
            {'op': 'add', 'path': '/copy/value/-', 'value': 'changed'},
        ]
        result, inverse = self.assert_application_roundtrip(doc, patch)
        self.assertEqual(result['source']['value'], ['original'])
        self.assertEqual(result['copy']['value'], ['original', 'changed'])

    def test_continuous_sequence_uses_every_operation(self):
        doc = {
            'items': ['a', 'b', 'c'],
            'obj': {'old': 0, 'target': 'before'},
            'target': 'old',
        }
        patch = [
            {'op': 'test', 'path': '/target', 'value': 'old'},
            {'op': 'add', 'path': '/obj/new', 'value': 1},
            {'op': 'add', 'path': '/items/-', 'value': 'd'},
            {'op': 'remove', 'path': '/items/0'},
            {'op': 'add', 'path': '/items/1', 'value': 'x'},
            {'op': 'replace', 'path': '/obj/old', 'value': 2},
            {'op': 'move', 'from': '/items/0', 'path': '/items/-'},
            {'op': 'move', 'from': '/obj/target', 'path': '/target'},
            {'op': 'copy', 'from': '/obj', 'path': '/obj_copy'},
            {'op': 'add', 'path': '/obj_copy/changed', 'value': True},
            {'op': 'test', 'path': '/obj_copy/old', 'value': 2},
        ]
        self.assert_application_roundtrip(doc, patch)

    def test_root_replace(self):
        doc = {'items': ['a', 'b']}
        patch = [
            {'op': 'add', 'path': '/items/-', 'value': 'c'},
            {'op': 'replace', 'path': '', 'value': [{'root': True}]},
        ]
        self.assert_application_roundtrip(doc, patch)

    def test_test_does_not_contribute_inverse_operation(self):
        result, inverse = jsonpatch.apply_with_inverse(
            {'foo': 'bar'},
            [
                {'op': 'test', 'path': '/foo', 'value': 'bar'},
                {'op': 'replace', 'path': '/foo', 'value': 'baz'},
                {'op': 'test', 'path': '/foo', 'value': 'baz'},
            ]
        )
        self.assertEqual(result, {'foo': 'baz'})
        self.assertEqual(inverse, [
            {'op': 'replace', 'path': '/foo', 'value': 'bar'},
        ])

    def test_failed_operation_returns_no_inverse(self):
        doc = {'foo': ['a']}
        original = copy.deepcopy(doc)
        with self.assertRaises(jsonpatch.JsonPatchConflict):
            jsonpatch.apply_with_inverse(doc, [
                {'op': 'add', 'path': '/foo/-', 'value': 'b'},
                {'op': 'remove', 'path': '/missing'},
            ])
        self.assertEqual(doc, original)

    def test_inverse_is_isolated_from_patch_and_result(self):
        old_value = {'nested': ['value']}
        new_value = {'nested': ['new']}
        doc = {'foo': old_value}
        patch = [{'op': 'replace', 'path': '/foo', 'value': new_value}]
        result, inverse = jsonpatch.apply_with_inverse(doc, patch)
        old_value['nested'].append('old mutation')
        new_value['nested'].append('patch mutation')
        result['foo']['nested'].append('result mutation')
        self.assertEqual(inverse[0]['value'], {'nested': ['value']})

    def test_random_documents(self):
        random.seed(1729)
        for _ in range(50):
            doc = self._make_document(2)
            patch = self._make_patch(doc, 24)
            self.assert_application_roundtrip(doc, patch)

    def _make_value(self, depth):
        choices = [None, True, False, 0, 1, 'alpha', 'beta', 'z']
        if depth > 0:
            choices.extend([
                [],
                {},
                [self._make_value(depth - 1) for _ in range(random.randrange(3))],
                {str(i): self._make_value(depth - 1)
                 for i in range(random.randrange(3))},
            ])
        return random.choice(choices)

    def _make_document(self, depth):
        if depth == 0 or random.random() < 0.3:
            return [self._make_value(depth - 1)
                    for _ in range(random.randrange(2, 5))]
        return {
            chr(ord('a') + index): self._make_value(depth - 1)
            for index in range(random.randrange(2, 5))
        }

    def _pointers(self, value, path=''):
        pointers = [path]
        if isinstance(value, dict):
            for key, item in value.items():
                child_path = path + '/' + key
                pointers.extend(self._pointers(item, child_path))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                child_path = path + '/' + str(index)
                pointers.extend(self._pointers(item, child_path))
        return pointers

    def _non_root_pointers(self, doc):
        return [path for path in self._pointers(doc) if path]

    def _container_pointers(self, value, path=''):
        pointers = [(path, value)]
        if isinstance(value, dict):
            for key, item in value.items():
                pointers.extend(
                    self._container_pointers(item, path + '/' + key)
                )
        elif isinstance(value, list):
            for index, item in enumerate(value):
                pointers.extend(
                    self._container_pointers(item, path + '/' + str(index))
                )
        return pointers

    def _target_path(self, container, container_path):
        if isinstance(container, list):
            index = random.randrange(len(container) + 1)
            if container_path:
                return container_path + '/' + str(index)
            return '/' + str(index)
        key = random.choice(['z', 'q', 'm', 'n'])
        if container_path:
            return container_path + '/' + key
        return '/' + key

    def _make_patch(self, doc, operation_count):
        current = copy.deepcopy(doc)
        patch = []
        seen_operations = set()
        operations = ['add', 'remove', 'replace', 'move', 'copy', 'test']

        for _ in range(operation_count):
            op = random.choice(operations)
            operation = self._make_operation(op, current)
            if operation is None:
                continue

            trial = copy.deepcopy(current)
            try:
                current = jsonpatch.apply_patch(trial, [operation])
            except (jsonpatch.JsonPatchException, jsonpointer.JsonPointerException):
                continue

            patch.append(operation)
            seen_operations.add(op)

        for op in operations:
            if op not in seen_operations:
                operation = self._make_operation(op, current)
                if operation is not None:
                    trial = copy.deepcopy(current)
                    try:
                        current = jsonpatch.apply_patch(trial, [operation])
                    except (jsonpatch.JsonPatchException, jsonpointer.JsonPointerException):
                        continue
                    patch.append(operation)

        return patch

    def _make_operation(self, op, doc):
        if op == 'add':
            containers = self._container_pointers(doc)
            container_path, container = random.choice(containers)
            return {
                'op': 'add',
                'path': self._target_path(container, container_path),
                'value': self._make_value(1),
            }

        pointers = self._non_root_pointers(doc)
        if not pointers:
            return None
        path = random.choice(pointers)

        if op == 'remove':
            return {'op': 'remove', 'path': path}

        if op == 'replace':
            return {
                'op': 'replace',
                'path': path,
                'value': self._make_value(1),
            }

        if op == 'test':
            return {
                'op': 'test',
                'path': path,
                'value': copy.deepcopy(jsonpointer.resolve_pointer(doc, path)),
            }

        destination_pointers = self._non_root_pointers(doc)
        from_path = random.choice(destination_pointers)
        containers = self._container_pointers(doc)
        container_path, container = random.choice(containers)
        to_path = self._target_path(container, container_path)
        return {
            'op': op,
            'from': from_path,
            'path': to_path,
        }


class EqualityTestCase(unittest.TestCase):

    def test_patch_equality(self):
        patch1 = jsonpatch.JsonPatch([{ "op": "add", "path": "/a/b/c", "value": "foo" }])
        patch2 = jsonpatch.JsonPatch([{ "path": "/a/b/c", "op": "add", "value": "foo" }])
        self.assertEqual(patch1, patch2)


    def test_patch_unequal(self):
        patch1 = jsonpatch.JsonPatch([{'op': 'test', 'path': '/test'}])
        patch2 = jsonpatch.JsonPatch([{'op': 'test', 'path': '/test1'}])
        self.assertNotEqual(patch1, patch2)

    def test_patch_hash_equality(self):
        patch1 = jsonpatch.JsonPatch([{ "op": "add", "path": "/a/b/c", "value": "foo" }])
        patch2 = jsonpatch.JsonPatch([{ "path": "/a/b/c", "op": "add", "value": "foo" }])
        self.assertEqual(hash(patch1), hash(patch2))


    def test_patch_hash_unequal(self):
        patch1 = jsonpatch.JsonPatch([{'op': 'test', 'path': '/test'}])
        patch2 = jsonpatch.JsonPatch([{'op': 'test', 'path': '/test1'}])
        self.assertNotEqual(hash(patch1), hash(patch2))


    def test_patch_neq_other_objs(self):
        p = [{'op': 'test', 'path': '/test'}]
        patch = jsonpatch.JsonPatch(p)
        # a patch will always compare not-equal to objects of other types
        self.assertFalse(patch == p)
        self.assertFalse(patch == None)

        # also a patch operation will always compare
        # not-equal to objects of other types
        op = jsonpatch.PatchOperation(p[0])
        self.assertFalse(op == p[0])
        self.assertFalse(op == None)

    def test_str(self):
        patch_obj = [ { "op": "add", "path": "/child", "value": { "grandchild": { } } } ]
        patch = jsonpatch.JsonPatch(patch_obj)

        self.assertEqual(json.dumps(patch_obj), str(patch))
        self.assertEqual(json.dumps(patch_obj), patch.to_string())


def custom_types_dumps(obj):
    def default(obj):
        if isinstance(obj, decimal.Decimal):
            return {'__decimal__': str(obj)}
        raise TypeError('Unknown type')

    return json.dumps(obj, default=default)


def custom_types_loads(obj):
    def as_decimal(dct):
        if '__decimal__' in dct:
            return decimal.Decimal(dct['__decimal__'])
        return dct

    return json.loads(obj, object_hook=as_decimal)


class CustomTypesJsonPatch(jsonpatch.JsonPatch):
    @staticmethod
    def json_dumper(obj):
        return custom_types_dumps(obj)

    @staticmethod
    def json_loader(obj):
        return custom_types_loads(obj)


class MakePatchTestCase(unittest.TestCase):

    def test_apply_patch_to_copy(self):
        src = {'foo': 'bar', 'boo': 'qux'}
        dst = {'baz': 'qux', 'foo': 'boo'}
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertTrue(src is not res)

    def test_apply_patch_to_same_instance(self):
        src = {'foo': 'bar', 'boo': 'qux'}
        dst = {'baz': 'qux', 'foo': 'boo'}
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src, in_place=True)
        self.assertTrue(src is res)

    def test_objects(self):
        src = {'foo': 'bar', 'boo': 'qux'}
        dst = {'baz': 'qux', 'foo': 'boo'}
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_arrays(self):
        src = {'numbers': [1, 2, 3], 'other': [1, 3, 4, 5]}
        dst = {'numbers': [1, 3, 4, 5], 'other': [1, 3, 4]}
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_complex_object(self):
        src = {'data': [
            {'foo': 1}, {'bar': [1, 2, 3]}, {'baz': {'1': 1, '2': 2}}
        ]}
        dst = {'data': [
            {'foo': [42]}, {'bar': []}, {'baz': {'boo': 'oom!'}}
        ]}
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_array_add_remove(self):
        # see https://github.com/stefankoegl/python-json-patch/issues/4
        src = {'numbers': [], 'other': [1, 5, 3, 4]}
        dst = {'numbers': [1, 3, 4, 5], 'other': []}
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_add_nested(self):
        # see http://tools.ietf.org/html/draft-ietf-appsawg-json-patch-03#appendix-A.10
        src = {"foo": "bar"}
        patch_obj = [ { "op": "add", "path": "/child", "value": { "grandchild": { } } } ]
        res = jsonpatch.apply_patch(src, patch_obj)
        expected = { "foo": "bar",
                      "child": { "grandchild": { } }
                   }
        self.assertEqual(expected, res)

    # TODO: this test is currently disabled, as the optimized patch is
    # not ideal
    def _test_should_just_add_new_item_not_rebuild_all_list(self):
        src = {'foo': [1, 2, 3]}
        dst = {'foo': [3, 1, 2, 3]}
        patch = list(jsonpatch.make_patch(src, dst))
        self.assertEqual(len(patch), 1)
        self.assertEqual(patch[0]['op'], 'add')
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_escape(self):
        src = {"x/y": 1}
        dst = {"x/y": 2}
        patch = jsonpatch.make_patch(src, dst)
        self.assertEqual([{"path": "/x~1y", "value": 2, "op": "replace"}], patch.patch)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_root_list(self):
        """ Test making and applying a patch of the root is a list """
        src = [{'foo': 'bar', 'boo': 'qux'}]
        dst = [{'baz': 'qux', 'foo': 'boo'}]
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_make_patch_unicode(self):
        """ Test if unicode keys and values are handled correctly """
        src = {}
        dst = {'\xee': '\xee'}
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_issue40(self):
        """ Tests an issue in _split_by_common_seq reported in #40 """

        src = [8, 7, 2, 1, 0, 9, 4, 3, 5, 6]
        dest = [7, 2, 1, 0, 9, 4, 3, 6, 5, 8]
        jsonpatch.make_patch(src, dest)

    def test_issue76(self):
        """ Make sure op:remove does not include a 'value' field """

        src = { "name": "fred", "friend": "barney", "spouse": "wilma" }
        dst = { "name": "fred", "spouse": "wilma" }
        expected = [{"path": "/friend", "op": "remove"}]
        patch = jsonpatch.make_patch(src, dst)
        self.assertEqual(patch.patch, expected)
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_json_patch(self):
        old = {
            'queue': {'teams_out': [{'id': 3, 'reason': 'If tied'}, {'id': 5, 'reason': 'If tied'}]},
        }
        new = {
            'queue': {'teams_out': [{'id': 5, 'reason': 'If lose'}]}
        }
        patch = jsonpatch.make_patch(old, new)
        new_from_patch = jsonpatch.apply_patch(old, patch)
        self.assertEqual(new, new_from_patch)

    def test_arrays_one_element_sequences(self):
        """ Tests the case of multiple common one element sequences inside an array """
        # see https://github.com/stefankoegl/python-json-patch/issues/30#issuecomment-155070128
        src = [1,2,3]
        dst = [3,1,4,2]
        patch = jsonpatch.make_patch(src, dst)
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_list_in_dict(self):
        """ Test patch creation with a list within a dict, as reported in #74

        https://github.com/stefankoegl/python-json-patch/issues/74 """
        old = {'key': [{'someNumber': 0, 'someArray': [1, 2, 3]}]}
        new = {'key': [{'someNumber': 0, 'someArray': [1, 2, 3, 4]}]}
        patch = jsonpatch.make_patch(old, new)
        new_from_patch = jsonpatch.apply_patch(old, patch)
        self.assertEqual(new, new_from_patch)

    def test_nested(self):
        """ Patch creation with nested dicts, as reported in #41

        https://github.com/stefankoegl/python-json-patch/issues/41 """
        old = {'school':{'names':['Kevin','Carl']}}
        new = {'school':{'names':['Carl','Kate','Kevin','Jake']}}
        patch = jsonpatch.JsonPatch.from_diff(old, new)
        new_from_patch = jsonpatch.apply_patch(old, patch)
        self.assertEqual(new, new_from_patch)

    def test_move_from_numeric_to_alpha_dict_key(self):
        #https://github.com/stefankoegl/python-json-patch/issues/97
        src = {'13': 'x'}
        dst = {'A': 'a', 'b': 'x'}
        patch = jsonpatch.make_patch(src, dst)
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_issue90(self):
        """In JSON 1 is different from True even though in python 1 == True"""
        src = {'A': 1}
        dst = {'A': True}
        patch = jsonpatch.make_patch(src, dst)
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)
        self.assertIsInstance(res['A'], bool)

    def test_issue129(self):
        """In JSON 1 is different from True even though in python 1 == True Take Two"""
        src = {'A': {'D': 1.0}, 'B': {'E': 'a'}}
        dst = {'A': {'C': 'a'}, 'B': {'C': True}}
        patch = jsonpatch.make_patch(src, dst)
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)
        self.assertIsInstance(res['B']['C'], bool)

    def test_issue103(self):
        """In JSON 1 is different from 1.0 even though in python 1 == 1.0"""
        src = {'A': 1}
        dst = {'A': 1.0}
        patch = jsonpatch.make_patch(src, dst)
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)
        self.assertIsInstance(res['A'], float)

    def test_issue119(self):
        """Make sure it avoids casting numeric str dict key to int"""
        src = [
            {'foobar': {u'1': [u'lettuce', u'cabbage', u'bok choy', u'broccoli'], u'3': [u'ibex'], u'2': [u'apple'], u'5': [], u'4': [u'gerenuk', u'duiker'], u'10_1576156603109': [], u'6': [], u'8_1572034252560': [u'thompson', u'gravie', u'mango', u'coconut'], u'7_1572034204585': []}},
            {'foobar':{u'description': u'', u'title': u''}}
        ]
        dst = [
            {'foobar': {u'9': [u'almond'], u'10': u'yes', u'12': u'', u'16_1598876845275': [], u'7': [u'pecan']}},
            {'foobar': {u'1': [u'lettuce', u'cabbage', u'bok choy', u'broccoli'], u'3': [u'ibex'], u'2': [u'apple'], u'5': [], u'4': [u'gerenuk', u'duiker'], u'10_1576156603109': [], u'6': [], u'8_1572034252560': [u'thompson', u'gravie', u'mango', u'coconut'], u'7_1572034204585': []}},
            {'foobar': {u'description': u'', u'title': u''}}
        ]
        patch = jsonpatch.make_patch(src, dst)
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_issue120(self):
        """Make sure it avoids casting numeric str dict key to int"""
        src = [{'foobar': {'821b7213_b9e6_2b73_2e9c_cf1526314553': ['Open Work'],
                '6e3d1297_0c5a_88f9_576b_ad9216611c94': ['Many Things'],
                '1987bcf0_dc97_59a1_4c62_ce33e51651c7': ['Product']}},
            {'foobar': {'2a7624e_0166_4d75_a92c_06b3f': []}},
            {'foobar': {'10': [],
                '11': ['bee',
                'ant',
                'wasp'],
                '13': ['phobos',
                'titan',
                'gaea'],
                '14': [],
                '15': 'run3',
                '16': 'service',
                '2': ['zero', 'enable']}}]
        dst = [{'foobar': {'1': [], '2': []}},
            {'foobar': {'821b7213_b9e6_2b73_2e9c_cf1526314553': ['Open Work'],
                '6e3d1297_0c5a_88f9_576b_ad9216611c94': ['Many Things'],
                '1987bcf0_dc97_59a1_4c62_ce33e51651c7': ['Product']}},
            {'foobar': {'2a7624e_0166_4d75_a92c_06b3f': []}},
            {'foobar': {'b238d74d_dcf4_448c_9794_c13a2f7b3c0a': [],
                'dcb0387c2_f7ae_b8e5bab_a2b1_94deb7c': []}},
            {'foobar': {'10': [],
                '11': ['bee',
                'ant',
                'fly'],
                '13': ['titan',
                'phobos',
                'gaea'],
                '14': [],
                '15': 'run3',
                '16': 'service',
                '2': ['zero', 'enable']}}
        ]
        patch = jsonpatch.make_patch(src, dst)
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_custom_types_diff(self):
        old = {'value': decimal.Decimal('1.0')}
        new = {'value': decimal.Decimal('1.00')}
        generated_patch = jsonpatch.JsonPatch.from_diff(
            old, new,  dumps=custom_types_dumps)
        str_patch = generated_patch.to_string(dumps=custom_types_dumps)
        loaded_patch = jsonpatch.JsonPatch.from_string(
            str_patch, loads=custom_types_loads)
        self.assertEqual(generated_patch, loaded_patch)
        new_from_patch = jsonpatch.apply_patch(old, generated_patch)
        self.assertEqual(new, new_from_patch)

    def test_custom_types_subclass(self):
        old = {'value': decimal.Decimal('1.0')}
        new = {'value': decimal.Decimal('1.00')}
        generated_patch = CustomTypesJsonPatch.from_diff(old, new)
        str_patch = generated_patch.to_string()
        loaded_patch = CustomTypesJsonPatch.from_string(str_patch)
        self.assertEqual(generated_patch, loaded_patch)
        new_from_patch = jsonpatch.apply_patch(old, loaded_patch)
        self.assertEqual(new, new_from_patch)

    def test_custom_types_subclass_load(self):
        old = {'value': decimal.Decimal('1.0')}
        new = {'value': decimal.Decimal('1.00')}
        patch = CustomTypesJsonPatch.from_string(
            '[{"op": "replace", "path": "/value", "value": {"__decimal__": "1.00"}}]')
        new_from_patch = jsonpatch.apply_patch(old, patch)
        self.assertEqual(new, new_from_patch)


class OptimizationTests(unittest.TestCase):
    def test_use_replace_instead_of_remove_add(self):
        src = {'foo': [1, 2, 3]}
        dst = {'foo': [3, 2, 3]}
        patch = list(jsonpatch.make_patch(src, dst))
        self.assertEqual(len(patch), 1)
        self.assertEqual(patch[0]['op'], 'replace')
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_use_replace_instead_of_remove_add_nested(self):
        src = {'foo': [{'bar': 1, 'baz': 2}, {'bar': 2, 'baz': 3}]}
        dst = {'foo': [{'bar': 1}, {'bar': 2, 'baz': 3}]}
        patch = list(jsonpatch.make_patch(src, dst))

        exp = [{'op': 'remove', 'path': '/foo/0/baz'}]
        self.assertEqual(patch, exp)

        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_use_move_instead_of_remove_add(self):
        src = {'foo': [4, 1, 2, 3]}
        dst = {'foo': [1, 2, 3, 4]}
        patch = list(jsonpatch.make_patch(src, dst))
        self.assertEqual(len(patch), 1)
        self.assertEqual(patch[0]['op'], 'move')
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_use_move_instead_of_add_remove(self):
        def fn(_src, _dst):
            patch = list(jsonpatch.make_patch(_src, _dst))
            # Check if there are only 'move' operations
            for p in patch:
                self.assertEqual(p['op'], 'move')
            res = jsonpatch.apply_patch(_src, patch)
            self.assertEqual(res, _dst)

        fn({'foo': [1, 2, 3]}, {'foo': [3, 1, 2]})
        fn([1, 2, 3], [3, 1, 2])
        fn({'foo': [1, 2, 3]}, {'foo': [3, 2, 1]})
        fn([1, 2, 3], [3, 2, 1])

    def test_success_if_replace_inside_dict(self):
        src = [{'a': 1, 'foo': {'b': 2, 'd': 5}}]
        dst = [{'a': 1, 'foo': {'b': 3, 'd': 6}}]
        patch = jsonpatch.make_patch(src, dst)
        self.assertEqual(patch.apply(src), dst)

    def test_success_if_replace_single_value(self):
        src = [{'a': 1, 'b': 2, 'd': 5}]
        dst = [{'a': 1, 'c': 3, 'd': 5}]
        patch = jsonpatch.make_patch(src, dst)
        self.assertEqual(patch.apply(src), dst)

    def test_success_if_replaced_by_object(self):
        src = [{'a': 1, 'b': 2, 'd': 5}]
        dst = [{'d': 6}]
        patch = jsonpatch.make_patch(src, dst)
        self.assertEqual(patch.apply(src), dst)

    def test_success_if_correct_patch_appied(self):
        src = [{'a': 1}, {'b': 2}]
        dst = [{'a': 1, 'b': 2}]
        patch = jsonpatch.make_patch(src, dst)
        self.assertEqual(patch.apply(src), dst)

    def test_success_if_correct_expected_patch_appied(self):
        src = [{"a": 1, "b": 2}]
        dst = [{"b": 2, "c": 2}]
        exp = [
            {'path': '/0/a', 'op': 'remove'},
            {'path': '/0/c', 'op': 'add', 'value': 2}
        ]
        patch = jsonpatch.make_patch(src, dst)
        self.assertEqual(patch.patch, exp)
        # verify that this patch does what we expect
        res = jsonpatch.apply_patch(src, patch)
        self.assertEqual(res, dst)

    def test_minimal_patch(self):
        """ Test whether a minimal patch is created, see #36 """
        src = [{"foo": 1, "bar": 2}]
        dst = [{"foo": 2, "bar": 2}]

        patch = jsonpatch.make_patch(src, dst)

        exp = [
            {
                "path": "/0/foo",
                "value": 2,
                "op": "replace"
            }
        ]

        self.assertEqual(patch.patch, exp)


class ListTests(unittest.TestCase):

    def test_fail_prone_list_1(self):
        """ Test making and applying a patch of the root is a list """
        src = ['a', 'r', 'b']
        dst = ['b', 'o']
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_fail_prone_list_2(self):
        """ Test making and applying a patch of the root is a list """
        src = ['a', 'r', 'b', 'x', 'm', 'n']
        dst = ['b', 'o', 'm', 'n']
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_fail_prone_list_3(self):
        """ Test making and applying a patch of the root is a list """
        src = ['boo1', 'bar', 'foo1', 'qux']
        dst = ['qux', 'bar']
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)

    def test_fail_prone_list_4(self):
        """ Test making and applying a patch of the root is a list """
        src = ['bar1', 59, 'foo1', 'foo']
        dst = ['foo', 'bar', 'foo1']
        patch = jsonpatch.make_patch(src, dst)
        res = patch.apply(src)
        self.assertEqual(res, dst)


class InvalidInputTests(unittest.TestCase):

    def test_missing_op(self):
        # an "op" member is required
        src = {"foo": "bar"}
        patch_obj = [ { "path": "/child", "value": { "grandchild": { } } } ]
        self.assertRaises(jsonpatch.JsonPatchException, jsonpatch.apply_patch, src, patch_obj)


    def test_invalid_op(self):
        # "invalid" is not a valid operation
        src = {"foo": "bar"}
        patch_obj = [ { "op": "invalid", "path": "/child", "value": { "grandchild": { } } } ]
        self.assertRaises(jsonpatch.JsonPatchException, jsonpatch.apply_patch, src, patch_obj)


class ConflictTests(unittest.TestCase):

    def test_remove_indexerror(self):
        src = {"foo": [1, 2]}
        patch_obj = [ { "op": "remove", "path": "/foo/10"} ]
        self.assertRaises(jsonpatch.JsonPatchConflict, jsonpatch.apply_patch, src, patch_obj)

    def test_remove_keyerror(self):
        src = {"foo": [1, 2]}
        patch_obj = [ { "op": "remove", "path": "/foo/b"} ]
        self.assertRaises(jsonpointer.JsonPointerException, jsonpatch.apply_patch, src, patch_obj)

    def test_remove_keyerror_dict(self):
        src = {'foo': {'bar': 'barz'}}
        patch_obj = [ { "op": "remove", "path": "/foo/non-existent"} ]
        self.assertRaises(jsonpatch.JsonPatchConflict, jsonpatch.apply_patch, src, patch_obj)

    def test_insert_oob(self):
        src = {"foo": [1, 2]}
        patch_obj = [ { "op": "add", "path": "/foo/10", "value": 1} ]
        self.assertRaises(jsonpatch.JsonPatchConflict, jsonpatch.apply_patch, src, patch_obj)

    def test_move_into_child(self):
        src = {"foo": {"bar": {"baz": 1}}}
        patch_obj = [ { "op": "move", "from": "/foo", "path": "/foo/bar" } ]
        self.assertRaises(jsonpatch.JsonPatchException, jsonpatch.apply_patch, src, patch_obj)

    def test_replace_oob(self):
        src = {"foo": [1, 2]}
        patch_obj = [ { "op": "replace", "path": "/foo/10", "value": 10} ]
        self.assertRaises(jsonpatch.JsonPatchConflict, jsonpatch.apply_patch, src, patch_obj)

    def test_replace_oob_length(self):
        src = {"foo": [0, 1]}
        patch_obj = [ { "op": "replace", "path": "/foo/2", "value": 2} ]
        self.assertRaises(jsonpatch.JsonPatchConflict, jsonpatch.apply_patch, src, patch_obj)

    def test_replace_missing(self):
        src = {"foo": 1}
        patch_obj = [ { "op": "replace", "path": "/bar", "value": 10} ]
        self.assertRaises(jsonpatch.JsonPatchConflict, jsonpatch.apply_patch, src, patch_obj)


class JsonPointerTests(unittest.TestCase):

    def test_create_with_pointer(self):

        patch = jsonpatch.JsonPatch([
            {'op': 'add', 'path': jsonpointer.JsonPointer('/foo'), 'value': 'bar'},
            {'op': 'add', 'path': jsonpointer.JsonPointer('/baz'), 'value': [1, 2, 3]},
            {'op': 'remove', 'path': jsonpointer.JsonPointer('/baz/1')},
            {'op': 'test', 'path': jsonpointer.JsonPointer('/baz'), 'value': [1, 3]},
            {'op': 'replace', 'path': jsonpointer.JsonPointer('/baz/0'), 'value': 42},
            {'op': 'remove', 'path': jsonpointer.JsonPointer('/baz/1')},
            {'op': 'move', 'from': jsonpointer.JsonPointer('/foo'), 'path': jsonpointer.JsonPointer('/bar')},

        ])
        doc = {}
        result = patch.apply(doc)
        expected = {'bar': 'bar', 'baz': [42]}
        self.assertEqual(result, expected)


class JsonPatchCreationTest(unittest.TestCase):

    def test_creation_fails_with_invalid_patch(self):
        invalid_patches = [
            {             'path': '/foo', 'value': 'bar'},
            {'op': 0xADD, 'path': '/foo', 'value': 'bar'},
            {'op': 'boo', 'path': '/foo', 'value': 'bar'},
            {'op': 'add',                 'value': 'bar'},
        ]
        for patch in invalid_patches:
            with self.assertRaises(jsonpatch.InvalidJsonPatch):
                jsonpatch.JsonPatch([patch])

        with self.assertRaises(jsonpointer.JsonPointerException):
            jsonpatch.JsonPatch([{'op': 'add', 'path': 'foo', 'value': 'bar'}])


class UtilityMethodTests(unittest.TestCase):

    def test_boolean_coercion(self):
        empty_patch = jsonpatch.JsonPatch([])
        self.assertFalse(empty_patch)

    def test_patch_equality(self):
        p = jsonpatch.JsonPatch([{'op': 'add', 'path': '/foo', 'value': 'bar'}])
        q = jsonpatch.JsonPatch([{'op': 'add', 'path': '/foo', 'value': 'bar'}])
        different_op = jsonpatch.JsonPatch([{'op': 'remove', 'path': '/foo'}])
        different_path = jsonpatch.JsonPatch([{'op': 'add', 'path': '/bar', 'value': 'bar'}])
        different_value = jsonpatch.JsonPatch([{'op': 'add', 'path': '/foo', 'value': 'foo'}])
        self.assertNotEqual(p, different_op)
        self.assertNotEqual(p, different_path)
        self.assertNotEqual(p, different_value)
        self.assertEqual(p, q)

    def test_operation_equality(self):
        add = jsonpatch.AddOperation({'path': '/new-element', 'value': 'new-value'})
        add2 = jsonpatch.AddOperation({'path': '/new-element', 'value': 'new-value'})
        rm = jsonpatch.RemoveOperation({'path': '/target'})
        self.assertEqual(add, add2)
        self.assertNotEqual(add, rm)

    def test_add_operation_structure(self):
        with self.assertRaises(jsonpatch.InvalidJsonPatch):
            jsonpatch.AddOperation({'path': '/'}).apply({})

    def test_replace_operation_structure(self):
        with self.assertRaises(jsonpatch.InvalidJsonPatch):
            jsonpatch.ReplaceOperation({'path': '/'}).apply({})

        with self.assertRaises(jsonpatch.InvalidJsonPatch):
            jsonpatch.ReplaceOperation({'path': '/top/-', 'value': 'foo'}).apply({'top': {'inner': 'value'}})

        with self.assertRaises(jsonpatch.JsonPatchConflict):
            jsonpatch.ReplaceOperation({'path': '/top/missing', 'value': 'foo'}).apply({'top': {'inner': 'value'}})

    def test_move_operation_structure(self):
        with self.assertRaises(jsonpatch.InvalidJsonPatch):
            jsonpatch.MoveOperation({'path': '/target'}).apply({})

        with self.assertRaises(jsonpatch.JsonPatchConflict):
            jsonpatch.MoveOperation({'from': '/source', 'path': '/target'}).apply({})

    def test_test_operation_structure(self):
        with self.assertRaises(jsonpatch.JsonPatchTestFailed):
            jsonpatch.TestOperation({'path': '/target'}).apply({})

        with self.assertRaises(jsonpatch.InvalidJsonPatch):
            jsonpatch.TestOperation({'path': '/target'}).apply({'target': 'value'})

    def test_copy_operation_structure(self):
        with self.assertRaises(jsonpatch.InvalidJsonPatch):
            jsonpatch.CopyOperation({'path': '/target'}).apply({})

        with self.assertRaises(jsonpatch.JsonPatchConflict):
            jsonpatch.CopyOperation({'path': '/target', 'from': '/source'}).apply({})

        with self.assertRaises(jsonpatch.JsonPatchConflict):
            jsonpatch.CopyOperation({'path': '/target', 'from': '/source'}).apply({})


class CustomJsonPointer(jsonpointer.JsonPointer):
    pass


class PrefixJsonPointer(jsonpointer.JsonPointer):
    def __init__(self, pointer):
        super(PrefixJsonPointer, self).__init__('/foo/bar' + pointer)


class CustomJsonPointerTests(unittest.TestCase):

    def test_json_patch_from_string(self):
        patch = '[{"op": "add", "path": "/baz", "value": "qux"}]'
        res = jsonpatch.JsonPatch.from_string(
            patch, pointer_cls=CustomJsonPointer,
        )
        self.assertEqual(res.pointer_cls, CustomJsonPointer)

    def test_json_patch_from_object(self):
        patch = [{'op': 'add', 'path': '/baz', 'value': 'qux'}]
        res = jsonpatch.JsonPatch(
            patch, pointer_cls=CustomJsonPointer,
        )
        self.assertEqual(res.pointer_cls, CustomJsonPointer)

    def test_json_patch_from_diff(self):
        old = {'foo': 'bar'}
        new = {'foo': 'baz'}
        res = jsonpatch.JsonPatch.from_diff(
            old, new, pointer_cls=CustomJsonPointer,
        )
        self.assertEqual(res.pointer_cls, CustomJsonPointer)

    def test_apply_patch_from_string(self):
        obj = {'foo': 'bar'}
        patch = '[{"op": "add", "path": "/baz", "value": "qux"}]'
        res = jsonpatch.apply_patch(
            obj, patch,
            pointer_cls=CustomJsonPointer,
        )
        self.assertTrue(obj is not res)
        self.assertTrue('baz' in res)
        self.assertEqual(res['baz'], 'qux')

    def test_apply_patch_from_object(self):
        obj = {'foo': 'bar'}
        res = jsonpatch.apply_patch(
            obj, [{'op': 'add', 'path': '/baz', 'value': 'qux'}],
            pointer_cls=CustomJsonPointer,
        )
        self.assertTrue(obj is not res)

    def test_make_patch(self):
        src = {'foo': 'bar', 'boo': 'qux'}
        dst = {'baz': 'qux', 'foo': 'boo'}
        patch = jsonpatch.make_patch(
            src, dst, pointer_cls=CustomJsonPointer,
        )
        res = patch.apply(src)
        self.assertTrue(src is not res)
        self.assertEqual(patch.pointer_cls, CustomJsonPointer)
        self.assertTrue(patch._ops)
        for op in patch._ops:
            self.assertIsInstance(op.pointer, CustomJsonPointer)
            self.assertEqual(op.pointer_cls, CustomJsonPointer)

    def test_operations(self):
        operations =[
            (
                jsonpatch.AddOperation, {
                    'op': 'add', 'path': '/foo', 'value': [1, 2, 3]
                }
            ),
            (
                jsonpatch.MoveOperation, {
                    'op': 'move', 'path': '/baz', 'from': '/foo'
                },
            ),
            (
                jsonpatch.RemoveOperation, {
                    'op': 'remove', 'path': '/baz/1'
                },
            ),
            (
                jsonpatch.TestOperation, {
                    'op': 'test', 'path': '/baz', 'value': [1, 3]
                },
            ),
            (
                jsonpatch.ReplaceOperation, {
                    'op': 'replace', 'path': '/baz/0', 'value': 42
                },
            ),
            (
                jsonpatch.RemoveOperation, {
                    'op': 'remove', 'path': '/baz/1'
                },
            )
        ]
        for cls, patch in operations:
            operation = cls(patch, pointer_cls=CustomJsonPointer)
            self.assertEqual(operation.pointer_cls, CustomJsonPointer)
            self.assertIsInstance(operation.pointer, CustomJsonPointer)

    def test_operations_from_patch(self):
        patch = jsonpatch.JsonPatch([
            {'op': 'add', 'path': '/foo', 'value': [1, 2, 3]},
            {'op': 'move', 'path': '/baz', 'from': '/foo'},
            {'op': 'add', 'path': '/baz', 'value': [1, 2, 3]},
            {'op': 'remove', 'path': '/baz/1'},
            {'op': 'test', 'path': '/baz', 'value': [1, 3]},
            {'op': 'replace', 'path': '/baz/0', 'value': 42},
            {'op': 'remove', 'path': '/baz/1'},
        ], pointer_cls=CustomJsonPointer)
        self.assertEqual(patch.apply({}), {'baz': [42]})
        self.assertEqual(patch.pointer_cls, CustomJsonPointer)
        self.assertTrue(patch._ops)
        for op in patch._ops:
            self.assertIsInstance(op.pointer, CustomJsonPointer)
            self.assertEqual(op.pointer_cls, CustomJsonPointer)

    def test_json_patch_with_prefix_pointer(self):
        res = jsonpatch.apply_patch(
            {'foo': {'bar': {}}}, [{'op': 'add', 'path': '/baz', 'value': 'qux'}],
            pointer_cls=PrefixJsonPointer,
        )
        self.assertEqual(res, {'foo': {'bar': {'baz': 'qux'}}})


class CustomOperationTests(unittest.TestCase):

    def test_custom_operation(self):

        class IdentityOperation(jsonpatch.PatchOperation):
            def apply(self, obj):
                return obj

        class JsonPatch(jsonpatch.JsonPatch):
            operations = MappingProxyType(
                dict(
                    identity=IdentityOperation,
                    **jsonpatch.JsonPatch.operations
                )
            )

        patch = JsonPatch([{'op': 'identity', 'path': '/'}])
        self.assertIn('identity', patch.operations)
        res = patch.apply({})
        self.assertEqual(res, {})


if __name__ == '__main__':
    modules = ['jsonpatch']


    def get_suite():
        suite = unittest.TestSuite()
        suite.addTest(doctest.DocTestSuite(jsonpatch))
        suite.addTest(unittest.makeSuite(ApplyPatchTestCase))
        suite.addTest(unittest.makeSuite(ApplyWithInverseTestCase))
        suite.addTest(unittest.makeSuite(EqualityTestCase))
        suite.addTest(unittest.makeSuite(MakePatchTestCase))
        suite.addTest(unittest.makeSuite(ListTests))
        suite.addTest(unittest.makeSuite(InvalidInputTests))
        suite.addTest(unittest.makeSuite(ConflictTests))
        suite.addTest(unittest.makeSuite(OptimizationTests))
        suite.addTest(unittest.makeSuite(JsonPointerTests))
        suite.addTest(unittest.makeSuite(JsonPatchCreationTest))
        suite.addTest(unittest.makeSuite(UtilityMethodTests))
        suite.addTest(unittest.makeSuite(CustomJsonPointerTests))
        suite.addTest(unittest.makeSuite(CustomOperationTests))
        return suite


    suite = get_suite()

    for module in modules:
        m = __import__(module, fromlist=[module])
        suite.addTest(doctest.DocTestSuite(m))

    runner = unittest.TextTestRunner(verbosity=1)

    result = runner.run(suite)

    if not result.wasSuccessful():
        sys.exit(1)
