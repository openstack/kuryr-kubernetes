# Copyright 2018 Red Hat
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock

from oslo_serialization import jsonutils
import six

from kuryr_kubernetes.cmd import status
from kuryr_kubernetes import constants
from kuryr_kubernetes.objects import vif
from kuryr_kubernetes.tests import base as test_base


class TestStatusCmd(test_base.TestCase):
    def setUp(self):
        super(TestStatusCmd, self).setUp()
        self.cmd = status.UpgradeCommands()

    def test_upgrade_result_get_details(self):
        res = status.UpgradeCheckResult(0, 'a ' * 50)

        self.assertEqual(
            (('a ' * 30).rstrip() + '\n' + (' ' * 9) + ('a ' * 20)).rstrip(),
            res.get_details())

    def test__get_annotation_missing(self):
        pod = {
            'metadata': {
                'annotations': {}
            }
        }

        self.assertIsNone(self.cmd._get_annotation(pod))

    def test__get_annotation_existing(self):
        mock_obj = vif.PodState(
            default_vif=vif.VIFMacvlanNested(vif_name='foo'))

        pod = {
            'metadata': {
                'annotations': {
                    constants.K8S_ANNOTATION_VIF: jsonutils.dumps(
                        mock_obj.obj_to_primitive())
                }
            }
        }

        obj = self.cmd._get_annotation(pod)
        self.assertEqual(mock_obj, obj)

    @mock.patch('sys.stdout', new_callable=six.StringIO)
    def _test_upgrade_check(self, code, code_name, m_stdout):
        method_success_m = mock.Mock()
        method_success_m.return_value = status.UpgradeCheckResult(0, 'foo')
        method_code_m = mock.Mock()
        method_code_m.return_value = status.UpgradeCheckResult(code, 'bar')

        self.cmd.check_methods = {'baz': method_success_m,
                                  'blah': method_code_m}
        self.assertEqual(code, self.cmd.upgrade_check())

        output = m_stdout.getvalue()
        self.assertIn('baz', output)
        self.assertIn('bar', output)
        self.assertIn('foo', output)
        self.assertIn('blah', output)
        self.assertIn('Success', output)
        self.assertIn(code_name, output)

    def test_upgrade_check_success(self):
        self._test_upgrade_check(0, 'Success')

    def test_upgrade_check_warning(self):
        self._test_upgrade_check(1, 'Warning')

    def test_upgrade_check_failure(self):
        self._test_upgrade_check(2, 'Failure')

    def _test__check_annotations(self, ann_objs, code):
        pods = {
            'items': [
                {
                    'metadata': {
                        'annotations': {
                            constants.K8S_ANNOTATION_VIF: ann
                        }
                    }
                } for ann in ann_objs
            ]
        }
        self.cmd.k8s = mock.Mock(get=mock.Mock(return_value=pods))
        res = self.cmd._check_annotations()
        self.assertEqual(code, res.code)

    def test__check_annotations_succeed(self):
        ann_objs = [
            vif.PodState(default_vif=vif.VIFMacvlanNested(vif_name='foo')),
            vif.PodState(default_vif=vif.VIFMacvlanNested(vif_name='bar')),
        ]
        ann_objs = [jsonutils.dumps(ann.obj_to_primitive())
                    for ann in ann_objs]

        self._test__check_annotations(ann_objs, 0)

    def test__check_annotations_failure(self):
        ann_objs = [
            vif.PodState(default_vif=vif.VIFMacvlanNested(vif_name='foo')),
            vif.VIFMacvlanNested(vif_name='bar'),
        ]
        ann_objs = [jsonutils.dumps(ann.obj_to_primitive())
                    for ann in ann_objs]

        self._test__check_annotations(ann_objs, 2)

    def test__check_annotations_malformed_and_old(self):
        ann_objs = [
            vif.PodState(default_vif=vif.VIFMacvlanNested(vif_name='foo')),
            vif.VIFMacvlanNested(vif_name='bar'),
        ]
        ann_objs = [jsonutils.dumps(ann.obj_to_primitive())
                    for ann in ann_objs]
        ann_objs.append('{}')

        self._test__check_annotations(ann_objs, 2)

    def test__check_annotations_malformed(self):
        ann_objs = [
            vif.PodState(default_vif=vif.VIFMacvlanNested(vif_name='foo')),
        ]
        ann_objs = [jsonutils.dumps(ann.obj_to_primitive())
                    for ann in ann_objs]
        ann_objs.append('{}')

        self._test__check_annotations(ann_objs, 1)

    def _test__convert_annotations(self, method, calls):
        self.cmd.k8s.annotate = mock.Mock()

        ann_objs = [
            ('foo',
             vif.PodState(default_vif=vif.VIFMacvlanNested(vif_name='foo'))),
            ('bar', vif.VIFMacvlanNested(vif_name='bar')),
        ]
        ann_objs = [(name, jsonutils.dumps(ann.obj_to_primitive()))
                    for name, ann in ann_objs]

        pods = {
            'items': [
                {
                    'metadata': {
                        'annotations': {
                            constants.K8S_ANNOTATION_VIF: ann
                        },
                        'selfLink': name,
                        'resourceVersion': 1,
                    }
                } for name, ann in ann_objs
            ]
        }
        self.cmd.k8s = mock.Mock(get=mock.Mock(return_value=pods))
        method()
        for args in calls:
            self.cmd.k8s.annotate.assert_any_call(*args)

    def test_update_annotations(self):
        self._test__convert_annotations(self.cmd.update_annotations,
                                        [('bar', mock.ANY, 1)])

    def test_downgrade_annotations(self):
        self._test__convert_annotations(self.cmd.downgrade_annotations,
                                        [('foo', mock.ANY, 1)])
