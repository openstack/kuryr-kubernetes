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
    cfg.StrOpt('bind_address',
               help=_('Bind address for CNI daemon HTTP server. It is '
                      'recommened to allow only local connections.'),
               default='127.0.0.1:5036'),
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
               default=os.environ.get('K8S_API', 'https://localhost:6443')),
    cfg.StrOpt('ssl_client_crt_file',
               help=_("Absolute path to client cert to "
                      "connect to HTTPS K8S_API")),
    cfg.StrOpt('ssl_client_key_file',
               help=_("Absolute path client key file to "
                      "connect to HTTPS K8S_API")),
    cfg.StrOpt('ssl_ca_crt_file',
               help=_("Absolute path to ca cert file to "
                      "connect to HTTPS K8S_API"),
               default='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'),
    cfg.BoolOpt('ssl_verify_server_crt',
                help=_("HTTPS K8S_API server identity verification"),
                default=False),
    cfg.StrOpt('token_file',
               help=_("The token to talk to the k8s API"),
               default='/var/run/secrets/kubernetes.io/serviceaccount/token'),
    cfg.StrOpt('pod_project_driver',
               help=_("The driver to determine OpenStack project for pod "
                      "ports (default or annotation)"),
               default='default'),
    cfg.StrOpt('service_project_driver',
               help=_("The driver to determine OpenStack project for "
                      "services (default or annotation)"),
               default='default'),
    cfg.StrOpt('namespace_project_driver',
               help=_("The driver to determine OpenStack project for "
                      "namespaces (default or annotation)"),
               default='default'),
    cfg.StrOpt('network_policy_project_driver',
               help=_("The driver to determine OpenStack project for network "
                      "policies (default or annotation)"),
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
               default='lbaasv2'),
    cfg.StrOpt('endpoints_driver_octavia_provider',
               help=_("The Octavia load balancer provider that will be used "
                      "to support Kubernetes Endpoints"),
               default='default'),
    cfg.StrOpt('vif_pool_driver',
               help=_("The driver that manages VIFs pools for "
                      "Kubernetes Pods"),
               default='noop'),
    cfg.StrOpt('nodes_subnets_driver',
               help=_("The driver that manages listing K8s nodes subnet_ids."),
               default='config'),
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
    cfg.IntOpt('watch_connection_timeout',
               help=_('TCP connection timeout (in seconds) for the watcher '
                      'connections to K8s API.'),
               default=30),
    cfg.IntOpt('watch_read_timeout',
               help=_('TCP read timeout (in seconds) for the watcher '
                      'connections to K8s API. This affects reaction to time '
                      'when there are no events being streamed from K8s API. '
                      'When too low, Kuryr will reconnect more often. When '
                      'too high, Kuryr will take longer to reconnect when K8s '
                      'API stream was being silently broken.'),
               default=60),
    cfg.IntOpt('watch_reconcile_period',
               help=_('Period (in seconds) between iterations of fetching '
                      'full list of watched K8s API resources and putting '
                      'them into the enabled handlers. Setting 0 disables the '
                      'periodic reconciling. The reconciliation is done to '
                      'prevent Kuryr from missing events due to K8s API or '
                      'etcd issues.'),
               default=120),
    cfg.ListOpt('enabled_handlers',
                help=_("The comma-separated handlers that should be "
                       "registered for watching in the pipeline."),
                default=['vif', 'endpoints', 'service', 'kuryrloadbalancer',
                         'kuryrport']),
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
    cfg.StrOpt('additional_ifname_prefix',
               help=_("The prefix to use for additional vifs created by "
                      " multi_vif drivers"),
               default='eth'),
    cfg.BoolOpt('use_events',
                help=_('Use Kubernetes Events objects to indicate status of '
                       'Kuryr created OpenStack objects like networking for '
                       'pods (Neutron ports) or services (Octavia '
                       'loadbalancers). It might have impact on performance '
                       'on Kubernetes cluster, since all objects (so the '
                       'Event objects too) are stored on etcd.'),
                default=True),
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
               default=0,),
    cfg.IntOpt('lbaas_activation_timeout',
               help=_("Time (in seconds) that kuryr controller waits for "
                      "neutron LBaaS to be activated"),
               default=300),
    cfg.DictOpt('subnet_mapping',
                help=_("A mapping of default subnets for certain driverType "
                       "in a form of <driverType>:<SUBNET-ID>"),
                default={}),
    cfg.ListOpt('resource_tags',
                help=_("List of tags that will be applied to all OpenStack "
                       "(Neutron and Octavia) resources created by Kuryr. "
                       "This can be used to identify and garbage-collect "
                       "them when Kubernetes cluster Kuryr was serving is no "
                       "longer needed."),
                default=[]),
]

octavia_defaults = [
    cfg.StrOpt('member_mode',
               help=_("Define the communication mode between load balanacer "
                      "and its members"),
               default='L3'),
    cfg.BoolOpt('enforce_sg_rules',
                help=_("Enable the enforcement of SG rules at the LB SG "
                       "in case the LB does not maintain the source IP "
                       "of the caller resource"),
                default=True),
    cfg.StrOpt('lb_algorithm',
               help=_("The load-balancer algoritm that distributed traffic "
                      "to the pool members. The options are: ROUND_ROBIN, "
                      "LEAST_CONNECTIONS, SOURCE_IP and SOURCE_IP_PORT."),
               default='ROUND_ROBIN'),
    cfg.IntOpt('timeout_client_data',
               help=_("Frontend client inactivity timeout in milliseconds. "
                      "When set to 0, the default timeout value set by "
                      "Octavia is used."),
               default=0),
    cfg.IntOpt('timeout_member_data',
               help=_("Backend member inactivity timeout in milliseconds. "
                      "When set to 0, the default timeout value set by "
                      "Octavia is used."),
               default=0),
]

cache_defaults = [
    cfg.BoolOpt('enabled',
                help=_("Enable caching."),
                default=True),
    cfg.StrOpt('backend',
               help=_("Select backend cache option."),
               default="dogpile.cache.memory"),
]

nested_vif_driver_opts = [
    cfg.ListOpt('worker_nodes_subnets',
                help=_("Neutron subnet IDs for k8s worker node VMs."),
                default=[],
                deprecated_name='worker_nodes_subnet',
                deprecated_group='pod_vif_nested'),
    cfg.IntOpt('rev_update_attempts',
               help=_("How many time to try to re-update the neutron resource "
                      "when revision has been changed by other thread"),
               default=3),
]

vhostuser = [
    cfg.StrOpt('mount_point',
               help=_("Path where vhost-user port will be created "
                      "also it should be mount point for pod"),
               default='/var/cni/vhostuser'),
    cfg.StrOpt('ovs_vhu_path',
               help=_("Path where OVS keeps socket files for vhost-user "
                      "ports"),
               default='/var/run/openvswitch/')
]

prometheus_exporter_opts = [
    cfg.IntOpt('controller_exporter_port',
               help=_('port for the Controller Prometheus exporter.'),
               default=9654),
    cfg.IntOpt('cni_exporter_port',
               help=_('port for the CNI Prometheus exporter.'),
               default=9655)
]

CONF = cfg.CONF
CONF.register_opts(kuryr_k8s_opts)
CONF.register_opts(daemon_opts, group='cni_daemon')
CONF.register_opts(k8s_opts, group='kubernetes')
CONF.register_opts(neutron_defaults, group='neutron_defaults')
CONF.register_opts(octavia_defaults, group='octavia_defaults')
CONF.register_opts(cache_defaults, group='cache_defaults')
CONF.register_opts(nested_vif_driver_opts, group='pod_vif_nested')
CONF.register_opts(vhostuser, group='vhostuser')
CONF.register_opts(prometheus_exporter_opts, "prometheus_exporter")

CONF.register_opts(lib_config.core_opts)
CONF.register_opts(lib_config.binding_opts, 'binding')
lib_config.register_neutron_opts(CONF)

logging.register_options(CONF)


def init(args, **kwargs):
    version_k8s = version.version_info.version_string()
    CONF(args=args, project='kuryr-k8s', version=version_k8s, **kwargs)
    if os.environ.get('CNI_COMMAND') == 'VERSION':
        CONF.set_default('use_stderr', True)


def setup_logging():

    logging.setup(CONF, 'kuryr-kubernetes')
    logging.set_defaults(default_log_levels=logging.get_default_log_levels())
    version_k8s = version.version_info.version_string()
    LOG.info("Logging enabled!")
    LOG.info("%(prog)s version %(version)s",
             {'prog': sys.argv[0], 'version': version_k8s})
