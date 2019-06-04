package main

import (
	"encoding/json"
	"reflect"
)

const (
	vod = "versioned_object.data"
	ob  = "objects"
)

type VIF struct {
	Network Network `json:"network"`
	Address string  `json:"address"`
	VifName string  `json:"vif_name"`
}

type Network struct {
	Subnets []Subnet `json:"subnets"`
}

type Route struct {
	Cidr    string `json:"cidr"`
	Gateway string `json:"gateway"`
}

type IP struct {
	Address string `json:"address"`
}

type Subnet struct {
	Routes  []Route  `json:"routes"`
	Ips     []IP     `json:"ips"`
	Cidr    string   `json:"cidr"`
	Gateway string   `json:"gateway"`
	DNS     []string `json:"dns"`
}

func UnmarshalOVO(data []byte, r interface{}) error {
	// Unmarshall into a generic map
	var i map[string]interface{}
	if err := json.Unmarshal(data, &i); err != nil {
		return err
	}

	// Skip versioned_object.data level
	d := i[vod].(map[string]interface{})

	p := reflect.ValueOf(r) // this will be a pointer
	v := p.Elem()           // dereferences pointer
	t := v.Type()           // gets type of the struct

	// Go over fields of the struct
	for i := 0; i < t.NumField(); i++ {
		// Initial info
		field := t.Field(i)
		fieldVal := v.Field(i)
		key := field.Tag.Get("json")

		var obj interface{}

		// Main switch
		switch fieldVal.Kind() {
		case reflect.String:
			// In case of string let's just write it and we're done (hence continue)
			fieldVal.SetString(d[key].(string))
			continue
		case reflect.Slice:
			if reflect.ValueOf(d[key]).Kind() != reflect.Slice {
				// It's a list with next level of "versioned_object.data" and then "objects" keys. Let's flatten this.
				listObj := d[key].(map[string]interface{})
				listData := listObj[vod].(map[string]interface{})
				obj = listData[ob].([]interface{})
				break
			}
			// If we have a slice and d[key] is just a simple list, then struct's approach will work fine, that's
			// why there's this fallthrough.
			fallthrough
		case reflect.Struct:
			// Treat it as struct
			obj = d[key]
		}

		// For slices and structs marshall that level of JSON, and unmarshall them into the result. The weird
		// approach with reflect.New is forced by how reflections work in golang.
		jsonBytes, err := json.Marshal(obj)
		if err != nil {
			return err
		}
		new := reflect.New(fieldVal.Type())
		inter := new.Interface()
		if err := json.Unmarshal(jsonBytes, &inter); err != nil {
			return err
		}
		fieldVal.Set(new.Elem())
	}

	return nil
}

func (v *VIF) UnmarshalJSON(data []byte) error {
	return UnmarshalOVO(data, v)
}

func (v *Network) UnmarshalJSON(data []byte) error {
	return UnmarshalOVO(data, v)
}

func (v *Subnet) UnmarshalJSON(data []byte) error {
	return UnmarshalOVO(data, v)
}

func (v *IP) UnmarshalJSON(data []byte) error {
	return UnmarshalOVO(data, v)
}

func (v *Route) UnmarshalJSON(data []byte) error {
	return UnmarshalOVO(data, v)
}
