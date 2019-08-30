package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net"
	"net/http"

	"github.com/containernetworking/cni/pkg/skel"
	"github.com/containernetworking/cni/pkg/types"
	cni "github.com/containernetworking/cni/pkg/types"
	"github.com/containernetworking/cni/pkg/types/current"
	"github.com/containernetworking/cni/pkg/version"
	"github.com/pkg/errors"
)

const (
	// FIXME(dulek): We don't really have a good way to fetch current URL:port binding here.
	//               I'm hardcoding it for now, but in the future we should probably put it in
	//               the JSON config in 10-kuryr.conf file that we will get passed on stdin.
	urlBase = "http://localhost:5036/"
	addPath = "addNetwork"
	delPath = "delNetwork"
)

type KuryrDaemonData struct {
	IfName      string      `json:"CNI_IFNAME"`
	Netns       string      `json:"CNI_NETNS"`
	Path        string      `json:"CNI_PATH"`
	Command     string      `json:"CNI_COMMAND"`
	ContainerID string      `json:"CNI_CONTAINERID"`
	Args        string      `json:"CNI_ARGS"`
	KuryrConf   interface{} `json:"config_kuryr"`
}

func transformData(args *skel.CmdArgs, command string) (KuryrDaemonData, error) {
	var conf interface{}
	err := json.Unmarshal(args.StdinData, &conf)
	if err != nil {
		return KuryrDaemonData{}, err
	}

	return KuryrDaemonData{
		IfName:      args.IfName,
		Netns:       args.Netns,
		Path:        args.Path,
		Command:     command,
		ContainerID: args.ContainerID,
		Args:        args.Args,
		KuryrConf:   conf,
	}, nil
}

func makeDaemonRequest(data KuryrDaemonData, expectedCode int) ([]byte, error) {
	log.Print("Calling Kuryr Daemon.")

	b, err := json.Marshal(data)
	if err != nil {
		return []byte{}, errors.Wrapf(err, "Error when preparing payload for kuryr-daemon")
	}

	url := ""
	switch data.Command {
	case "ADD":
		url = urlBase + addPath
	case "DEL":
		url = urlBase + delPath
	default:
		return []byte{}, errors.Errorf("Cannot handle command %s", data.Command)
	}

	resp, err := http.Post(url, "application/json", bytes.NewBuffer(b))
	if err != nil {
		return []byte{}, errors.Wrapf(err, "Looks like %s cannot be reached. Is kuryr-daemon running?", url)
	}
	defer resp.Body.Close()

	body, _ := ioutil.ReadAll(resp.Body)
	if resp.StatusCode != expectedCode {
		return []byte{}, errors.Errorf("CNI Daemon returned error %d %s", resp.StatusCode, body)
	}

	return body, nil
}

func cmdAdd(args *skel.CmdArgs) error {
	data, err := transformData(args, "ADD")
	if err != nil {
		return errors.Wrap(err, "Error when reading configuration")
	}

	body, err := makeDaemonRequest(data, 202)
	if err != nil {
		return err
	}

	vif := VIF{}
	err = json.Unmarshal(body, &vif)
	if err != nil {
		return errors.Wrapf(err, "Error when reading response from kurry-daemon: %s", string(body))
	}

	iface := current.Interface{}
	iface.Name = args.IfName
	iface.Mac = vif.Address
	iface.Sandbox = args.ContainerID

	var ips []*current.IPConfig
	var dns types.DNS
	var routes []*types.Route
	for _, subnet := range vif.Network.Subnets {
		addrStr := subnet.Ips[0].Address
		addr := net.ParseIP(addrStr)
		if addr == nil {
			return errors.Errorf("Error when parsing IP address %s received from kuryr-daemon", addrStr)

		}
		_, cidr, err := net.ParseCIDR(subnet.Cidr)
		if err != nil {
			return errors.Wrapf(err, "Error when parsing CIDR %s received from kuryr-daemon",
				subnet.Cidr)
		}

		ver := "4"
		if addr.To4() == nil {
			ver = "6"
		}

		prefixSize, _ := cidr.Mask.Size()
		ifaceCIDR := fmt.Sprintf("%s/%d", addr.String(), prefixSize)
		ipAddress, err := cni.ParseCIDR(ifaceCIDR)
		if err != nil {
			return errors.Wrapf(err, "Error when parsing CIDR %s received from kuryr-daemon", ifaceCIDR)
		}
		ifaceNum := 0

		ips = append(ips, &current.IPConfig{
			Version:   ver,
			Interface: &ifaceNum,
			Gateway:   net.ParseIP(subnet.Gateway),
			Address:   *ipAddress,
		})

		for _, route := range subnet.Routes {
			_, dst, err := net.ParseCIDR(route.Cidr)
			if err != nil {
				return errors.Wrapf(err, "Error when parsing CIDR %s received from kuryr-daemon",
					route.Cidr)
			}

			gw := net.ParseIP(route.Gateway)
			if gw == nil {
				return errors.Errorf("Error when parsing IP address %s received from kuryr-daemon",
					route.Gateway)
			}

			routes = append(routes, &types.Route{Dst: *dst, GW: gw})
		}

		dns.Nameservers = append(dns.Nameservers, subnet.DNS...)
	}

	res := &current.Result{
		Interfaces: []*current.Interface{&iface},
		IPs:        ips,
		DNS:        dns,
		Routes:     routes,
	}

	return types.PrintResult(res, "0.3.1")
}

func cmdDel(args *skel.CmdArgs) error {
	data, err := transformData(args, "DEL")
	_, err = makeDaemonRequest(data, 204)
	return err
}

func cmdCheck(args *skel.CmdArgs) error {
	return nil
}

func main() {
	skel.PluginMain(cmdAdd, cmdCheck, cmdDel, version.All, "CNI Plugin Kuryr-Kubernetes v1.0.0")
}
