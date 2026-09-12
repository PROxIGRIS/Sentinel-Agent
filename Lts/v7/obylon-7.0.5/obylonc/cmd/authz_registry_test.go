package cmd

import (
	"strings"
	"testing"
)

func splitShortcut(value string) []string { return strings.Fields(value) }

func TestEveryPublicOperationalCommandHasScopeMetadata(t *testing.T) {
	for _, name := range commandOrder {
		entry := commands[name]
		if entry.brief == "" {
			t.Fatalf("%s missing brief", name)
		}
		if entry.scope == "" {
			t.Fatalf("%s missing scope", name)
		}
		if name != "activate" && entry.action == "" {
			t.Fatalf("%s missing action", name)
		}
	}
}

func TestAdminShortcutsResolveToKnownCommands(t *testing.T) {
	for shortcut, path := range adminShortcuts {
		parts := splitShortcut(path)
		if len(parts) == 0 {
			t.Fatalf("%s empty", shortcut)
		}
		_, ok := commands[parts[0]]
		if !ok {
			t.Fatalf("%s -> %s is not an admin command", shortcut, parts[0])
		}
	}
}

func TestEveryAdminOperationalCommandHasScopeMetadata(t *testing.T) {
	for name, entry := range adminOperational {
		if !entry.admin {
			t.Fatalf("%s is in admin registry without admin=true", name)
		}
		if entry.scope == "" {
			t.Fatalf("%s missing admin scope", name)
		}
	}
}

func TestAuthNamespaceCanResolveEveryAdminOperationalCommand(t *testing.T) {
	for name := range adminOperational {
		if _, ok := adminOperational[name]; !ok {
			t.Fatalf("%s missing from admin operational registry", name)
		}
	}
}

func TestEveryPublicCommandIsRepresentedByAdminScope(t *testing.T) {
	for _, name := range commandOrder {
		entry, ok := adminOperational[name]
		if !ok {
			t.Fatalf("%s has no admin-scope representation", name)
		}
		if entry.scope == "" {
			t.Fatalf("%s admin scope is empty", name)
		}
	}
}

func TestAdminOperationalActionsAreRegistered(t *testing.T) {
	for name, entry := range adminOperational {
		if name == "activate" {
			if entry.action != "obylon.license.activate" {
				t.Fatalf("activate action = %q", entry.action)
			}
			continue
		}
		if entry.action == "" {
			t.Fatalf("%s has no action metadata", name)
		}
	}
}
