package api

import (
	"encoding/json"
	"testing"
)

func TestActivateRequestCarriesNodeName(t *testing.T) {
	req := ActivateRequest{
		LicenseKey:          "OBY-TEST",
		Hostname:            "LAB-PC-17",
		NodeName:            "LAB-PC-17",
		DeviceName:          "LAB-PC-17",
		HardwareUUID:        "uuid",
		HardwareFingerprint: "fp",
		ExistingNodeID:      "existing-node",
	}
	payload := map[string]interface{}{
		"license_key": req.LicenseKey, "hostname": req.Hostname,
		"node_name": req.NodeName, "nodeName": req.NodeName,
		"device_name": req.DeviceName, "deviceName": req.DeviceName,
		"hardware_uuid": req.HardwareUUID, "hardware_fingerprint": req.HardwareFingerprint,
		"existing_node_id": req.ExistingNodeID,
	}
	b, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"node_name", "nodeName", "device_name", "deviceName", "hostname"} {
		if got[key] != "LAB-PC-17" {
			t.Fatalf("%s = %#v, want LAB-PC-17", key, got[key])
		}
	}
}
