package cmd

import (
	"strings"
	"testing"
)

func TestValidateBootTaskDefinitionAcceptsGeneratedUTF16Task(t *testing.T) {
	raw := utf16LEWithBOM(bootTaskXML(`C:\Program Files\Obylon\ObylonBroker.exe`))

	ok, message := validateBootTaskDefinition(raw)
	if !ok {
		t.Fatalf("generated task should validate, got: %s", message)
	}
}

func TestValidateBootTaskDefinitionRejectsMissingBootTrigger(t *testing.T) {
	xml := strings.Replace(
		bootTaskXML(`C:\Program Files\Obylon\ObylonBroker.exe`),
		"<Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>",
		"<Triggers></Triggers>",
		1,
	)

	ok, message := validateBootTaskDefinition(utf16LEWithBOM(xml))
	if ok || !strings.Contains(message, "boot trigger") {
		t.Fatalf("missing boot trigger must fail validation, got ok=%v message=%q", ok, message)
	}
}

func TestValidateBootTaskDefinitionRejectsMissingDuplicateSpawnProtection(t *testing.T) {
	xml := strings.Replace(
		bootTaskXML(`C:\Program Files\Obylon\ObylonBroker.exe`),
		"<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
		"<MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>",
		1,
	)

	ok, message := validateBootTaskDefinition(utf16LEWithBOM(xml))
	if ok || !strings.Contains(message, "duplicate-spawn prevention") {
		t.Fatalf("parallel task instances must fail validation, got ok=%v message=%q", ok, message)
	}
}

func TestDescribeBootTaskQueryFailureDistinguishesAccessDenied(t *testing.T) {
	message := describeBootTaskQueryFailure([]byte("ERROR: Access is denied."), errTaskQueryFailed{})
	if !strings.Contains(message, "denied access") {
		t.Fatalf("access-denied result must not be reported as missing, got %q", message)
	}
}

type errTaskQueryFailed struct{}

func (errTaskQueryFailed) Error() string { return "exit status 1" }
