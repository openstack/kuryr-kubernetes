# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import os
import sys

from kuryr.lib._i18n import _
from kuryr.lib import config as lib_config
from oslo_config import cfg
from oslo_log import log as logging

from kuryr_kubernetes import version

LOG = logging.getLogger(__name__)

kuryr_k8s_opts = [
    cfg.StrOpt('pybasedir',
               help=_('Directory where Kuryr-kubernetes python module is '
                      'installed.'),
               default=os.path.abspath(
                   os.path.join(os.path.dirname(__file__),
                                '../../'))),
]

daemon_opts = [
    cfg.BoolOpt('daemon_enabled',
                help=_('Enable CNI Daemon configuration.'),
                default=True,
                deprecated_for_removal=True,
                deprecated_reason="Deployment without kuryr-daemon is now "
                                  "deprecated.",
                deprecated_since="Rocky"),
    cfg.StrOpt('bind_address',
               help=_('Bind address for CNI daemon HTTP server. It is '
                      'recommened to allow only local connections.'),
               default='127.0.0.1:50036'),
    cfg.IntOpt('worker_num',
               help=_('Maximum number of processes that will be spawned to '
                      'process requests from CNI driver.'),
               default=30),
    cfg.IntOpt('vif_annotation_timeout',
               help=_('Time (in seconds) the CNI daemon will wait for VIF '
                      'annotation to appear in pod metadata before failing '
                      'the CNI request.'),
               default=60),
    cfg.IntOpt('pyroute2_timeout',
               help=_('Kuryr uses pyroute2 library to manipulate networking '
                      'interfaces. When processing a high number of Kuryr '
                      'requests in parallel, it may take kernel more time to '
                      'process all networking stack changes. This option '
                      'allows to tune internal pyroute2 timeout.'),
               default=10),
    cfg.BoolOpt('docker_mode',
                help=_('Set to True when you are running kuryr-daemon inside '
                       'a Docker container on Kubernetes host. E.g. as '
                       'DaemonSet on Kubernetes cluster Kuryr is supposed to '
                       'provide networking for. This mainly means that '
                       'kuryr-daemon will look for network namespaces in '
                       '$netns_proc_dir instead of /proc.'),
                default=False),
    cfg.StrOpt('netns_proc_dir',
               help=_("When docker_mode is set to True, this config option "
                      "should be set to where host's /proc directory is "
                      "mounted. Please note that mounting it is necessary to "
                      "allow Kuryr-Kubernetes to move host interfaces between "
                      "host network namespaces, which is essential for Kuryr "
                      "to work."),
               default=None),
    cfg.IntOpt('cni_failures_count',
               help=_('Maximum number of consecutive failures of kuryr-daemon '
                      'when processing requests. If this number is exceeded, '
                      'kuryr-daemon will be marked as unhealthy.'),
               default=3),
]

k8s_opts = [
    cfg.StrOpt('api_root',
               help=_("The root URL of the Kubernetes API"),
               default=os.environ.get('K8S_API', 'http://localhost:8080')),
    cfg.StrOpt('ssl_client_crt_file',
               help=_("Absolute path to client cert to "
                      "connect to HTTPS K8S_API")),
    cfg.StrOpt('ssl_client_key_file',
               help=_("Absolute path client key file to "
                      "connect to HTTPS K8S_API")),
    cfg.StrOpt('ssl_ca_crt_file',
               help=_("Absolute path to ca cert file to "
                      "connect to HTTPS K8S_API")),
    cfg.BoolOpt('ssl_verify_server_crt',
                help=_("HTTPS K8S_API server identity verification"),
                default=False),
    cfg.StrOpt('token_file',
               help=_("The token to talk to the k8s API"),
               default=''),
    cfg.StrOpt('pod_project_driver',
               help=_("The driver to determine OpenStack "
                      "project for pod ports"),
               default='default'),
    cfg.StrOpt('service_project_driver',
               help=_("The driver to determine OpenStack "
                      "project for services"),
               default='default'),
    cfg.StrOpt('namespace_project_driver',
               help=_("The driver to determine OpenStack "
                      "project for namespaces"),
               default='default'),
    cfg.StrOpt('network_policy_project_driver',
               help=_("The driver to determine OpenStack "
                      "project for network policies"),
               default='default'),
    cfg.StrOpt('pod_subnets_driver',
               help=_("The driver to determine Neutron "
                      "subnets for pod ports"),
               default='default'),
    cfg.StrOpt('service_subnets_driver',
               help=_("The driver to determine Neutron "
                      "subnets for services"),
               default='default'),
    cfg.StrOpt('pod_security_groups_driver',
               help=_("The driver to determine Neutron "
                      "security groups for pods"),
               default='default'),
    cfg.StrOpt('service_security_groups_driver',
               help=_("The driver to determine Neutron "
                      "security groups for services"),
               default='default'),
    cfg.StrOpt('pod_vif_driver',
               help=_("The driver that provides VIFs for Kubernetes Pods."),
               default='neutron-vif'),
    cfg.StrOpt('endpoints_lbaas_driver',
               help=_("The driver that provides LoadBalancers for "
                      "Kubernetes Endpoints"),
               default='lbaasv2',
               deprecated_for_removal=True,
               deprecated_reason="Default and supported lbaas endpoint is "
                                 "now Octavia",
               deprecated_since="Rocky"),
    cfg.StrOpt('endpoints_driver_octavia_provider',
               help=_("The Octavia load balancer provider that will be used "
                      "to support Kubernetes Endpoints"),
               default='default'),
    cfg.StrOpt('vif_pool_driver',
               help=_("The driver that manages VIFs pools for "
                      "Kubernetes Pods"),
               default='noop'),
    cfg.BoolOpt('port_debug',
                help=_('Enable port debug to force kuryr port names to be '
                       'set to their corresponding pod names.'),
                default=False),
    cfg.StrOpt('service_public_ip_driver',
               help=_("The driver that provides external IP for LB at "
                      "Kubernetes"),
               default='neutron_floating_ip'),
    cfg.BoolOpt('enable_manager',
                help=_("Enable Manager to manage the pools."),
                default=False),
    cfg.IntOpt('watch_retry_timeout',
               help=_('Time (in seconds) the watcher retries watching for.'),
               default=60),
    cfg.ListOpt('enabled_handlers',
                help=_("The comma-separated handlers that should be "
                       "registered for watching in the pipeline."),
                default=['vif', 'lb', 'lbaasspec']),
    cfg.BoolOpt('controller_ha',
                help=_('Enable kuryr-controller active/passive HA. Only '
                       'supported in containerized deployments on Kubernetes '
                       'or OpenShift.'),
                default=False),
    cfg.PortOpt('controller_ha_elector_port',
                help=_('Port on which leader-elector pod is listening to.'),
                default=16401),
    cfg.StrOpt('network_policy_driver',
               help=_("Driver for network policies"),
               default='default'),
    cfg.ListOpt('multi_vif_drivers',
                help=_("The drivers that provide additional VIFs for "
                       "Kubernetes Pods."),
                default='noop'),
]

neutron_defaults = [
    cfg.StrOpt('project',
               help=_("Default OpenStack project ID for "
                      "Kubernetes resources")),
    cfg.StrOpt('pod_subnet',
               help=_("Default Neutron subnet ID for Kubernetes pods")),
    cfg.ListOpt('pod_security_groups',
                help=_("Default Neutron security groups' IDs "
                       "for Kubernetes pods")),
    cfg.StrOpt('ovs_bridge',
               help=_("Default OpenVSwitch integration bridge"),
               sample_default="br-int"),
    cfg.StrOpt('service_subnet',
               help=_("Default Neutron subnet ID for Kubernetes services")),
    cfg.StrOpt('external_svc_net',
               help=_("Default external network ID for Kubernetes services")),
    cfg.StrOpt('external_svc_subnet',
               help=_("Optional external subnet ID for Kubernetes services"),
               default=None),
    cfg.IntOpt('network_device_mtu',
               help='Default MTU setting for network interface.',
               default=1500,),
    cfg.IntOpt('lbaas_activation_timeout',
               help=_("Time (in seconds) that kuryr controller waits for "
                      "neutron LBaaS to be activated"),
               default=300),
]

octavia_defaults = [
    cfg.StrOpt('member_mode',
               help=_("Define the communication mode between load balanacer "
                      "and its members"),
               default='L3'),
    cfg.StrOpt('sg_mode',
               help=_("Define the LBaaS SG policy."),
               choices=[('create', 'replace the VIP SG with a new one'),
                        ('update', 'add rules to the existing VIP SG')],
               default='update'),
]

cache_defaults = [
    cfg.BoolOpt('enabled',
                help=_("Enable caching."),
                default=True),
    cfg.StrOpt('backend',
               help=_("Select backend cache option."),
               default="dogpile.cache.memory"),
]

ingress = [
    cfg.StrOpt('l7_router_uuid',
               help=_("UUID of the L7 Router")),
]

nested_vif_driver_opts = [
    cfg.StrOpt('worker_nodes_subnet',
               help=_("Neutron subnet ID for k8s worker node vms."),
               default=''),
]

DEFAULT_PHYSNET_SUBNET_MAPPINGS = {}
DEFAULT_DEVICE_MAPPINGS = []
sriov_opts = [
    cfg.DictOpt('default_physnet_subnets',
                help=_("A mapping of default subnets for certain physnets "
                       "in a form of physnet-name:<SUBNET-ID>"),
                default=DEFAULT_PHYSNET_SUBNET_MAPPINGS),
    cfg.ListOpt('physical_device_mappings',
                default=DEFAULT_DEVICE_MAPPINGS,
                help=_("Comma-separated list of "
                       "<physical_network>:<network_device> tuples mapping "
                       "physical network names to the agent's node-specific "
                       "physical network device interfaces of SR-IOV physical "
                       "function to be used for VLAN networks.")),
]


CONF = cfg.CONF
CONF.register_opts(kuryr_k8s_opts)
CONF.register_opts(daemon_opts, group='cni_daemon')
CONF.register_opts(k8s_opts, group='kubernetes')
CONF.register_opts(neutron_defaults, group='neutron_defaults')
CONF.register_opts(octavia_defaults, group='octavia_defaults')
CONF.register_opts(cache_defaults, group='cache_defaults')
CONF.register_opts(ingress, group='ingress')
CONF.register_opts(nested_vif_driver_opts, group='pod_vif_nested')
CONF.register_opts(sriov_opts, group='sriov')

CONF.register_opts(lib_config.core_opts)
CONF.register_opts(lib_config.binding_opts, 'binding')
lib_config.register_neutron_opts(CONF)

logging.register_options(CONF)


def init(args, **kwargs):
    version_k8s = version.version_info.version_string()
    CONF(args=args, project='kuryr-k8s', version=version_k8s, **kwargs)


def setup_logging():

    logging.setup(CONF, 'kuryr-kubernetes')
    logging.set_defaults(default_log_levels=logging.get_default_log_levels())
    version_k8s = version.version_info.version_string()
    LOG.info("Logging enabled!")
    LOG.info("%(prog)s version %(version)s",
             {'prog': sys.argv[0], 'version': version_k8s})
