--
-- PostgreSQL database dump
--

\restrict eV2GTMfzT0Fq7erXgvK2UBfM1k9KSQp4AgBzhKD4Z8bf4HtEYfJVlo84Rtp2XAy

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.11 (Ubuntu 17.11-1.pgdg22.04+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

DROP POLICY IF EXISTS nodes_self_managed ON public.license_nodes;
DROP POLICY IF EXISTS fastlane_events_select_authenticated ON public.fastlane_events;
DROP POLICY IF EXISTS fastlane_events_insert_anon ON public.fastlane_events;
DROP POLICY IF EXISTS device_tokens_self_update ON public.device_tokens;
DROP POLICY IF EXISTS device_tokens_self_select ON public.device_tokens;
DROP POLICY IF EXISTS device_tokens_self_insert ON public.device_tokens;
DROP POLICY IF EXISTS device_tokens_self_delete ON public.device_tokens;
DROP POLICY IF EXISTS "activity_logs read auth" ON public.activity_logs;
DROP POLICY IF EXISTS "activity_logs insert service" ON public.activity_logs;
DROP POLICY IF EXISTS "Users view own unban" ON public.unban_requests;
DROP POLICY IF EXISTS "Users view own sessions" ON public.phone_otp_sessions;
DROP POLICY IF EXISTS "Users view own roles" ON public.user_roles;
DROP POLICY IF EXISTS "Users view own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users view own otp" ON public.phone_otp_sessions;
DROP POLICY IF EXISTS "Users view own ban" ON public.banned_users;
DROP POLICY IF EXISTS "Users update own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users read own roles" ON public.user_roles;
DROP POLICY IF EXISTS "Users insert own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users create unban" ON public.unban_requests;
DROP POLICY IF EXISTS "Users can view their own unban requests" ON public.unban_requests;
DROP POLICY IF EXISTS "Users can view their own sessions" ON public.user_sessions;
DROP POLICY IF EXISTS "Users can view their own preferences" ON public.user_preferences;
DROP POLICY IF EXISTS "Users can view their own ban status" ON public.banned_users;
DROP POLICY IF EXISTS "Users can view their own audit logs" ON public.security_audit_logs;
DROP POLICY IF EXISTS "Users can view own totp" ON public.user_totp;
DROP POLICY IF EXISTS "Users can view own linked devices" ON public.linked_devices;
DROP POLICY IF EXISTS "Users can view own device audit logs" ON public.device_audit_logs;
DROP POLICY IF EXISTS "Users can update their own sessions" ON public.user_sessions;
DROP POLICY IF EXISTS "Users can update their own preferences" ON public.user_preferences;
DROP POLICY IF EXISTS "Users can update own linked devices" ON public.linked_devices;
DROP POLICY IF EXISTS "Users can read own pairing sessions" ON public.pairing_sessions;
DROP POLICY IF EXISTS "Users can insert their own sessions" ON public.user_sessions;
DROP POLICY IF EXISTS "Users can insert their own preferences" ON public.user_preferences;
DROP POLICY IF EXISTS "Users can insert their own audit logs" ON public.security_audit_logs;
DROP POLICY IF EXISTS "Users can delete their own sessions" ON public.user_sessions;
DROP POLICY IF EXISTS "Teacher view profiles" ON public.profiles;
DROP POLICY IF EXISTS "Teacher manages helpers" ON public.user_roles;
DROP POLICY IF EXISTS "Staff view workstations" ON public.workstations;
DROP POLICY IF EXISTS "Staff view settings" ON public.system_settings;
DROP POLICY IF EXISTS "Staff view profiles" ON public.profiles;
DROP POLICY IF EXISTS "Staff view evidence" ON public.evidence_logs;
DROP POLICY IF EXISTS "Staff view apps" ON public.allowed_apps;
DROP POLICY IF EXISTS "Staff view alerts" ON public.alerts;
DROP POLICY IF EXISTS "Staff view agent configs" ON public.agent_configs;
DROP POLICY IF EXISTS "Staff view actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Service role full access" ON public.user_totp;
DROP POLICY IF EXISTS "Service role full access" ON public.phone_otp_sessions;
DROP POLICY IF EXISTS "Service full otp" ON public.phone_otp_sessions;
DROP POLICY IF EXISTS "Principal manages subordinate roles" ON public.user_roles;
DROP POLICY IF EXISTS "Own sessions update" ON public.user_sessions;
DROP POLICY IF EXISTS "Own sessions select" ON public.user_sessions;
DROP POLICY IF EXISTS "Own sessions insert" ON public.user_sessions;
DROP POLICY IF EXISTS "Own sessions delete" ON public.user_sessions;
DROP POLICY IF EXISTS "Own prefs update" ON public.user_preferences;
DROP POLICY IF EXISTS "Own prefs select" ON public.user_preferences;
DROP POLICY IF EXISTS "Own prefs insert" ON public.user_preferences;
DROP POLICY IF EXISTS "Own audit select" ON public.security_audit_logs;
DROP POLICY IF EXISTS "Own audit insert" ON public.security_audit_logs;
DROP POLICY IF EXISTS "Node Self Read License" ON public.licenses;
DROP POLICY IF EXISTS "Enable read access for app_categories" ON public.app_categories;
DROP POLICY IF EXISTS "Enable manage access for app_categories" ON public.app_categories;
DROP POLICY IF EXISTS "Elevated view unban" ON public.unban_requests;
DROP POLICY IF EXISTS "Elevated view banned" ON public.banned_users;
DROP POLICY IF EXISTS "Elevated view all profiles" ON public.profiles;
DROP POLICY IF EXISTS "Elevated update unban" ON public.unban_requests;
DROP POLICY IF EXISTS "Elevated update actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Elevated unban users" ON public.banned_users;
DROP POLICY IF EXISTS "Elevated select workstations" ON public.workstations;
DROP POLICY IF EXISTS "Elevated select system_settings" ON public.system_settings;
DROP POLICY IF EXISTS "Elevated select evidence_logs" ON public.evidence_logs;
DROP POLICY IF EXISTS "Elevated select device_tokens" ON public.device_tokens;
DROP POLICY IF EXISTS "Elevated select case_dossiers" ON public.case_dossiers;
DROP POLICY IF EXISTS "Elevated select allowed_apps" ON public.allowed_apps;
DROP POLICY IF EXISTS "Elevated select alerts" ON public.alerts;
DROP POLICY IF EXISTS "Elevated select agent_health" ON public.agent_health;
DROP POLICY IF EXISTS "Elevated select agent_configs" ON public.agent_configs;
DROP POLICY IF EXISTS "Elevated select activity_logs" ON public.activity_logs;
DROP POLICY IF EXISTS "Elevated select actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Elevated roles can view unban requests" ON public.unban_requests;
DROP POLICY IF EXISTS "Elevated roles can update unban requests" ON public.unban_requests;
DROP POLICY IF EXISTS "Elevated roles can unban users" ON public.banned_users;
DROP POLICY IF EXISTS "Elevated roles can ban users" ON public.banned_users;
DROP POLICY IF EXISTS "Elevated read window settings" ON public.unauthorized_window_settings;
DROP POLICY IF EXISTS "Elevated read all roles" ON public.user_roles;
DROP POLICY IF EXISTS "Elevated read agent configs" ON public.agent_configs;
DROP POLICY IF EXISTS "Elevated manage window settings" ON public.unauthorized_window_settings;
DROP POLICY IF EXISTS "Elevated manage agent configs" ON public.agent_configs;
DROP POLICY IF EXISTS "Elevated insert actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Elevated delete profiles" ON public.profiles;
DROP POLICY IF EXISTS "Elevated delete actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Elevated ban users" ON public.banned_users;
DROP POLICY IF EXISTS "Elevated audit select" ON public.security_audit_logs;
DROP POLICY IF EXISTS "Developer Manage Nodes" ON public.license_nodes;
DROP POLICY IF EXISTS "Developer Manage Licenses" ON public.licenses;
DROP POLICY IF EXISTS "Dev/Admin/Principal can view all banned users" ON public.banned_users;
DROP POLICY IF EXISTS "Dev manages all roles" ON public.user_roles;
DROP POLICY IF EXISTS "Bootstrap first privileged user" ON public.user_roles;
DROP POLICY IF EXISTS "Banned users can insert unban requests" ON public.unban_requests;
DROP POLICY IF EXISTS "Allow anon inserts on alerts" ON public.alerts;
DROP POLICY IF EXISTS "Allow anon insert" ON public.unauthorized_events;
DROP POLICY IF EXISTS "Agent select workstations" ON public.workstations;
DROP POLICY IF EXISTS "Agent select unauthorized events" ON public.unauthorized_events;
DROP POLICY IF EXISTS "Agent read config" ON public.agent_configs;
DROP POLICY IF EXISTS "Agent insert unauthorized events" ON public.unauthorized_events;
DROP POLICY IF EXISTS "Agent delete unauthorized events" ON public.unauthorized_events;
DROP POLICY IF EXISTS "Agent anon update workstations" ON public.workstations;
DROP POLICY IF EXISTS "Agent anon update system_settings" ON public.system_settings;
DROP POLICY IF EXISTS "Agent anon update evidence_logs" ON public.evidence_logs;
DROP POLICY IF EXISTS "Agent anon update evidence" ON public.evidence_logs;
DROP POLICY IF EXISTS "Agent anon update device_tokens" ON public.device_tokens;
DROP POLICY IF EXISTS "Agent anon update admin_actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Agent anon select workstations" ON public.workstations;
DROP POLICY IF EXISTS "Agent anon select system_settings" ON public.system_settings;
DROP POLICY IF EXISTS "Agent anon select allowed_apps" ON public.allowed_apps;
DROP POLICY IF EXISTS "Agent anon select agent_configs" ON public.agent_configs;
DROP POLICY IF EXISTS "Agent anon select admin_actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Agent anon insert workstations" ON public.workstations;
DROP POLICY IF EXISTS "Agent anon insert evidence_logs" ON public.evidence_logs;
DROP POLICY IF EXISTS "Agent anon insert evidence" ON public.evidence_logs;
DROP POLICY IF EXISTS "Agent anon insert device_tokens" ON public.device_tokens;
DROP POLICY IF EXISTS "Agent anon insert alerts" ON public.alerts;
DROP POLICY IF EXISTS "Agent anon insert agent_health" ON public.agent_health;
DROP POLICY IF EXISTS "Agent anon insert activity_logs" ON public.activity_logs;
DROP POLICY IF EXISTS "Agent anon insert activity" ON public.activity_logs;
DROP POLICY IF EXISTS "Admins view workstations" ON public.workstations;
DROP POLICY IF EXISTS "Admins view settings" ON public.system_settings;
DROP POLICY IF EXISTS "Admins view evidence" ON public.evidence_logs;
DROP POLICY IF EXISTS "Admins view apps" ON public.allowed_apps;
DROP POLICY IF EXISTS "Admins view all roles" ON public.user_roles;
DROP POLICY IF EXISTS "Admins view all profiles" ON public.profiles;
DROP POLICY IF EXISTS "Admins view alerts" ON public.alerts;
DROP POLICY IF EXISTS "Admins view agent health" ON public.agent_health;
DROP POLICY IF EXISTS "Admins manage workstations" ON public.workstations;
DROP POLICY IF EXISTS "Admins manage settings" ON public.system_settings;
DROP POLICY IF EXISTS "Admins manage evidence" ON public.evidence_logs;
DROP POLICY IF EXISTS "Admins manage apps" ON public.allowed_apps;
DROP POLICY IF EXISTS "Admins manage alerts" ON public.alerts;
DROP POLICY IF EXISTS "Admins manage agent configs" ON public.agent_configs;
DROP POLICY IF EXISTS "Admins can manage dossiers" ON public.case_dossiers;
DROP POLICY IF EXISTS "Admins can manage app_categories" ON public.app_categories;
ALTER TABLE IF EXISTS ONLY public.workstations DROP CONSTRAINT IF EXISTS workstations_owner_id_fkey;
ALTER TABLE IF EXISTS ONLY public.user_totp DROP CONSTRAINT IF EXISTS user_totp_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.user_sessions DROP CONSTRAINT IF EXISTS user_sessions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.user_roles DROP CONSTRAINT IF EXISTS user_roles_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.user_preferences DROP CONSTRAINT IF EXISTS user_preferences_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.unban_requests DROP CONSTRAINT IF EXISTS unban_requests_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.unban_requests DROP CONSTRAINT IF EXISTS unban_requests_resolved_by_fkey;
ALTER TABLE IF EXISTS ONLY public.unauthorized_events DROP CONSTRAINT IF EXISTS unauthorized_events_workstation_id_fkey;
ALTER TABLE IF EXISTS ONLY public.security_audit_logs DROP CONSTRAINT IF EXISTS security_audit_logs_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.profiles DROP CONSTRAINT IF EXISTS profiles_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.phone_otp_sessions DROP CONSTRAINT IF EXISTS phone_otp_sessions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.pairing_sessions DROP CONSTRAINT IF EXISTS pairing_sessions_initiator_id_fkey;
ALTER TABLE IF EXISTS ONLY public.linked_devices DROP CONSTRAINT IF EXISTS linked_devices_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.linked_devices DROP CONSTRAINT IF EXISTS linked_devices_pairing_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.license_nodes DROP CONSTRAINT IF EXISTS license_nodes_license_id_fkey;
ALTER TABLE IF EXISTS ONLY public.license_nodes DROP CONSTRAINT IF EXISTS license_nodes_auth_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.license_events DROP CONSTRAINT IF EXISTS license_events_node_id_fkey;
ALTER TABLE IF EXISTS ONLY public.license_events DROP CONSTRAINT IF EXISTS license_events_license_id_fkey;
ALTER TABLE IF EXISTS ONLY public.evidence_logs DROP CONSTRAINT IF EXISTS evidence_logs_alert_id_fkey;
ALTER TABLE IF EXISTS ONLY public.device_tokens DROP CONSTRAINT IF EXISTS device_tokens_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.device_audit_logs DROP CONSTRAINT IF EXISTS device_audit_logs_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.device_audit_logs DROP CONSTRAINT IF EXISTS device_audit_logs_pairing_session_id_fkey;
ALTER TABLE IF EXISTS ONLY public.device_audit_logs DROP CONSTRAINT IF EXISTS device_audit_logs_linked_device_id_fkey;
ALTER TABLE IF EXISTS ONLY public.case_dossiers DROP CONSTRAINT IF EXISTS case_dossiers_workstation_id_fkey;
ALTER TABLE IF EXISTS ONLY public.case_dossiers DROP CONSTRAINT IF EXISTS case_dossiers_created_by_fkey;
ALTER TABLE IF EXISTS ONLY public.case_dossiers DROP CONSTRAINT IF EXISTS case_dossiers_alert_id_fkey;
ALTER TABLE IF EXISTS ONLY public.banned_users DROP CONSTRAINT IF EXISTS banned_users_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.banned_users DROP CONSTRAINT IF EXISTS banned_users_banned_by_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_revocations DROP CONSTRAINT IF EXISTS authz_revocations_revoked_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_revocations DROP CONSTRAINT IF EXISTS authz_revocations_device_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_revocations DROP CONSTRAINT IF EXISTS authz_revocations_credential_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_requests DROP CONSTRAINT IF EXISTS authz_requests_requesting_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_requests DROP CONSTRAINT IF EXISTS authz_requests_device_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_requests DROP CONSTRAINT IF EXISTS authz_requests_approved_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_requests DROP CONSTRAINT IF EXISTS authz_requests_application_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_requests DROP CONSTRAINT IF EXISTS authz_requests_action_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_devices DROP CONSTRAINT IF EXISTS authz_devices_authorized_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_devices DROP CONSTRAINT IF EXISTS authz_devices_application_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_decisions DROP CONSTRAINT IF EXISTS authz_decisions_request_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_decisions DROP CONSTRAINT IF EXISTS authz_decisions_device_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_decisions DROP CONSTRAINT IF EXISTS authz_decisions_decided_by_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_decisions DROP CONSTRAINT IF EXISTS authz_decisions_action_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_credentials DROP CONSTRAINT IF EXISTS authz_credentials_request_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_credentials DROP CONSTRAINT IF EXISTS authz_credentials_issued_to_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_credentials DROP CONSTRAINT IF EXISTS authz_credentials_device_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_credentials DROP CONSTRAINT IF EXISTS authz_credentials_application_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_audit_events DROP CONSTRAINT IF EXISTS authz_audit_events_request_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_audit_events DROP CONSTRAINT IF EXISTS authz_audit_events_device_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_audit_events DROP CONSTRAINT IF EXISTS authz_audit_events_credential_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_audit_events DROP CONSTRAINT IF EXISTS authz_audit_events_application_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_audit_events DROP CONSTRAINT IF EXISTS authz_audit_events_actor_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_audit_events DROP CONSTRAINT IF EXISTS authz_audit_events_action_id_fkey;
ALTER TABLE IF EXISTS ONLY public.authz_actions DROP CONSTRAINT IF EXISTS authz_actions_application_id_fkey;
ALTER TABLE IF EXISTS ONLY public.alerts DROP CONSTRAINT IF EXISTS alerts_workstation_id_fkey;
ALTER TABLE IF EXISTS ONLY public.agent_configs DROP CONSTRAINT IF EXISTS agent_configs_workstation_id_fkey;
ALTER TABLE IF EXISTS ONLY public.admin_actions DROP CONSTRAINT IF EXISTS admin_actions_target_id_fkey;
ALTER TABLE IF EXISTS ONLY public.admin_actions DROP CONSTRAINT IF EXISTS admin_actions_issued_by_fkey;
ALTER TABLE IF EXISTS ONLY public.activity_logs DROP CONSTRAINT IF EXISTS activity_logs_workstation_id_fkey;
DROP TRIGGER IF EXISTS workstations_updated ON public.workstations;
DROP TRIGGER IF EXISTS unauthorized_window_settings_updated ON public.unauthorized_window_settings;
DROP TRIGGER IF EXISTS system_settings_updated ON public.system_settings;
DROP TRIGGER IF EXISTS profiles_updated ON public.profiles;
DROP TRIGGER IF EXISTS enforce_unauthorized_window_update ON public.unauthorized_events;
DROP TRIGGER IF EXISTS case_dossiers_updated ON public.case_dossiers;
DROP TRIGGER IF EXISTS authz_requests_updated_at ON public.authz_requests;
DROP TRIGGER IF EXISTS authz_devices_updated_at ON public.authz_devices;
DROP TRIGGER IF EXISTS authz_applications_updated_at ON public.authz_applications;
DROP TRIGGER IF EXISTS authz_actions_updated_at ON public.authz_actions;
DROP TRIGGER IF EXISTS allowed_apps_updated ON public.allowed_apps;
DROP TRIGGER IF EXISTS alerts_critical_notify ON public.alerts;
DROP TRIGGER IF EXISTS agent_configs_updated ON public.agent_configs;
DROP INDEX IF EXISTS public.profiles_verified_telegram_chat_uidx;
DROP INDEX IF EXISTS public.profiles_verified_phone_uidx;
DROP INDEX IF EXISTS public.phone_otp_sessions_user_purpose_unique;
DROP INDEX IF EXISTS public.phone_otp_sessions_user_purpose_uidx;
DROP INDEX IF EXISTS public.phone_otp_sessions_token_hash_unique;
DROP INDEX IF EXISTS public.phone_otp_sessions_telegram_lookup;
DROP INDEX IF EXISTS public.phone_otp_sessions_telegram_link_chat_uidx;
DROP INDEX IF EXISTS public.phone_otp_sessions_login_phone_uidx;
DROP INDEX IF EXISTS public.idx_phone_otp_sessions_user_id;
DROP INDEX IF EXISTS public.idx_phone_otp_sessions_expires;
DROP INDEX IF EXISTS public.idx_pairing_sessions_token;
DROP INDEX IF EXISTS public.idx_pairing_sessions_expires;
DROP INDEX IF EXISTS public.idx_pairing_sessions_code;
DROP INDEX IF EXISTS public.idx_linked_devices_user;
DROP INDEX IF EXISTS public.idx_licenses_key_hash;
DROP INDEX IF EXISTS public.idx_license_nodes_license_id;
DROP INDEX IF EXISTS public.idx_license_nodes_hardware_fingerprint;
DROP INDEX IF EXISTS public.idx_device_audit_logs_user;
DROP INDEX IF EXISTS public.idx_case_dossiers_workstation;
DROP INDEX IF EXISTS public.idx_alerts_workstation;
DROP INDEX IF EXISTS public.idx_alerts_timestamp;
DROP INDEX IF EXISTS public.fastlane_events_workstation_id_idx;
DROP INDEX IF EXISTS public.fastlane_events_received_at_idx;
DROP INDEX IF EXISTS public.device_tokens_user_idx;
DROP INDEX IF EXISTS public.authz_revocations_device_idx;
DROP INDEX IF EXISTS public.authz_revocations_credential_idx;
DROP INDEX IF EXISTS public.authz_requests_status_expiry_idx;
DROP INDEX IF EXISTS public.authz_requests_requesting_user_idx;
DROP INDEX IF EXISTS public.authz_requests_identity_idx;
DROP INDEX IF EXISTS public.authz_requests_device_idx;
DROP INDEX IF EXISTS public.authz_devices_status_idx;
DROP INDEX IF EXISTS public.authz_devices_identity_idx;
DROP INDEX IF EXISTS public.authz_decisions_request_idx;
DROP INDEX IF EXISTS public.authz_credentials_identity_idx;
DROP INDEX IF EXISTS public.authz_credentials_device_idx;
DROP INDEX IF EXISTS public.authz_credentials_active_idx;
DROP INDEX IF EXISTS public.authz_audit_events_device_idx;
DROP INDEX IF EXISTS public.authz_audit_events_created_idx;
DROP INDEX IF EXISTS public.authz_audit_events_actor_idx;
DROP INDEX IF EXISTS public.admin_actions_target_status_idx;
DROP INDEX IF EXISTS public.activity_logs_ws_created_idx;
DROP INDEX IF EXISTS public.activity_logs_anomaly_idx;
ALTER TABLE IF EXISTS ONLY public.workstations DROP CONSTRAINT IF EXISTS workstations_pkey;
ALTER TABLE IF EXISTS ONLY public.workstations DROP CONSTRAINT IF EXISTS workstations_hardware_uuid_key;
ALTER TABLE IF EXISTS ONLY public.user_totp DROP CONSTRAINT IF EXISTS user_totp_pkey;
ALTER TABLE IF EXISTS ONLY public.user_sessions DROP CONSTRAINT IF EXISTS user_sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.user_roles DROP CONSTRAINT IF EXISTS user_roles_user_id_role_key;
ALTER TABLE IF EXISTS ONLY public.user_roles DROP CONSTRAINT IF EXISTS user_roles_pkey;
ALTER TABLE IF EXISTS ONLY public.user_preferences DROP CONSTRAINT IF EXISTS user_preferences_pkey;
ALTER TABLE IF EXISTS ONLY public.unban_requests DROP CONSTRAINT IF EXISTS unban_requests_pkey;
ALTER TABLE IF EXISTS ONLY public.unauthorized_window_settings DROP CONSTRAINT IF EXISTS unauthorized_window_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.unauthorized_events DROP CONSTRAINT IF EXISTS unauthorized_events_pkey;
ALTER TABLE IF EXISTS ONLY public.system_settings DROP CONSTRAINT IF EXISTS system_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.security_audit_logs DROP CONSTRAINT IF EXISTS security_audit_logs_pkey;
ALTER TABLE IF EXISTS ONLY public.profiles DROP CONSTRAINT IF EXISTS profiles_user_id_key;
ALTER TABLE IF EXISTS ONLY public.profiles DROP CONSTRAINT IF EXISTS profiles_pkey;
ALTER TABLE IF EXISTS ONLY public.phone_otp_sessions DROP CONSTRAINT IF EXISTS phone_otp_sessions_user_id_key;
ALTER TABLE IF EXISTS ONLY public.phone_otp_sessions DROP CONSTRAINT IF EXISTS phone_otp_sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.pairing_sessions DROP CONSTRAINT IF EXISTS pairing_sessions_token_key;
ALTER TABLE IF EXISTS ONLY public.pairing_sessions DROP CONSTRAINT IF EXISTS pairing_sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.linked_devices DROP CONSTRAINT IF EXISTS linked_devices_pkey;
ALTER TABLE IF EXISTS ONLY public.licenses DROP CONSTRAINT IF EXISTS licenses_pkey;
ALTER TABLE IF EXISTS ONLY public.licenses DROP CONSTRAINT IF EXISTS licenses_key_hash_key;
ALTER TABLE IF EXISTS ONLY public.license_nodes DROP CONSTRAINT IF EXISTS license_nodes_pkey;
ALTER TABLE IF EXISTS ONLY public.license_nodes DROP CONSTRAINT IF EXISTS license_nodes_license_id_hardware_uuid_key;
ALTER TABLE IF EXISTS ONLY public.license_events DROP CONSTRAINT IF EXISTS license_events_pkey;
ALTER TABLE IF EXISTS ONLY public.fastlane_events DROP CONSTRAINT IF EXISTS fastlane_events_pkey;
ALTER TABLE IF EXISTS ONLY public.evidence_logs DROP CONSTRAINT IF EXISTS evidence_logs_pkey;
ALTER TABLE IF EXISTS ONLY public.device_tokens DROP CONSTRAINT IF EXISTS device_tokens_token_key;
ALTER TABLE IF EXISTS ONLY public.device_tokens DROP CONSTRAINT IF EXISTS device_tokens_pkey;
ALTER TABLE IF EXISTS ONLY public.device_audit_logs DROP CONSTRAINT IF EXISTS device_audit_logs_pkey;
ALTER TABLE IF EXISTS ONLY public.case_dossiers DROP CONSTRAINT IF EXISTS case_dossiers_pkey;
ALTER TABLE IF EXISTS ONLY public.banned_users DROP CONSTRAINT IF EXISTS banned_users_pkey;
ALTER TABLE IF EXISTS ONLY public.authz_revocations DROP CONSTRAINT IF EXISTS authz_revocations_pkey;
ALTER TABLE IF EXISTS ONLY public.authz_requests DROP CONSTRAINT IF EXISTS authz_requests_user_code_hash_key;
ALTER TABLE IF EXISTS ONLY public.authz_requests DROP CONSTRAINT IF EXISTS authz_requests_pkey;
ALTER TABLE IF EXISTS ONLY public.authz_requests DROP CONSTRAINT IF EXISTS authz_requests_device_code_hash_key;
ALTER TABLE IF EXISTS ONLY public.authz_devices DROP CONSTRAINT IF EXISTS authz_devices_pkey;
ALTER TABLE IF EXISTS ONLY public.authz_devices DROP CONSTRAINT IF EXISTS authz_devices_application_id_device_fingerprint_key;
ALTER TABLE IF EXISTS ONLY public.authz_decisions DROP CONSTRAINT IF EXISTS authz_decisions_pkey;
ALTER TABLE IF EXISTS ONLY public.authz_credentials DROP CONSTRAINT IF EXISTS authz_credentials_token_jti_key;
ALTER TABLE IF EXISTS ONLY public.authz_credentials DROP CONSTRAINT IF EXISTS authz_credentials_pkey;
ALTER TABLE IF EXISTS ONLY public.authz_credentials DROP CONSTRAINT IF EXISTS authz_credentials_access_token_hash_key;
ALTER TABLE IF EXISTS ONLY public.authz_audit_events DROP CONSTRAINT IF EXISTS authz_audit_events_pkey;
ALTER TABLE IF EXISTS ONLY public.authz_applications DROP CONSTRAINT IF EXISTS authz_applications_slug_key;
ALTER TABLE IF EXISTS ONLY public.authz_applications DROP CONSTRAINT IF EXISTS authz_applications_pkey;
ALTER TABLE IF EXISTS ONLY public.authz_actions DROP CONSTRAINT IF EXISTS authz_actions_pkey;
ALTER TABLE IF EXISTS ONLY public.app_categories DROP CONSTRAINT IF EXISTS app_categories_pkey;
ALTER TABLE IF EXISTS ONLY public.app_categories DROP CONSTRAINT IF EXISTS app_categories_name_key;
ALTER TABLE IF EXISTS ONLY public.allowed_apps DROP CONSTRAINT IF EXISTS allowed_apps_process_name_key;
ALTER TABLE IF EXISTS ONLY public.allowed_apps DROP CONSTRAINT IF EXISTS allowed_apps_pkey;
ALTER TABLE IF EXISTS ONLY public.alerts DROP CONSTRAINT IF EXISTS alerts_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_health DROP CONSTRAINT IF EXISTS agent_health_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_configs DROP CONSTRAINT IF EXISTS agent_configs_pkey;
ALTER TABLE IF EXISTS ONLY public.admin_actions DROP CONSTRAINT IF EXISTS admin_actions_pkey;
ALTER TABLE IF EXISTS ONLY public.activity_logs DROP CONSTRAINT IF EXISTS activity_logs_pkey;
DROP TABLE IF EXISTS public.workstations;
DROP TABLE IF EXISTS public.user_totp;
DROP TABLE IF EXISTS public.user_sessions;
DROP TABLE IF EXISTS public.user_roles;
DROP TABLE IF EXISTS public.user_preferences;
DROP TABLE IF EXISTS public.unban_requests;
DROP TABLE IF EXISTS public.unauthorized_window_settings;
DROP TABLE IF EXISTS public.unauthorized_events;
DROP TABLE IF EXISTS public.system_settings;
DROP TABLE IF EXISTS public.security_audit_logs;
DROP TABLE IF EXISTS public.profiles_obylon_pre_fix_v2;
DROP TABLE IF EXISTS public.profiles_obylon_pre_fix;
DROP TABLE IF EXISTS public.profiles;
DROP TABLE IF EXISTS public.phone_otp_sessions_obylon_pre_fix_v2;
DROP TABLE IF EXISTS public.phone_otp_sessions_obylon_pre_fix;
DROP TABLE IF EXISTS public.phone_otp_sessions;
DROP TABLE IF EXISTS public.pairing_sessions;
DROP TABLE IF EXISTS public.linked_devices;
DROP TABLE IF EXISTS public.license_nodes;
DROP TABLE IF EXISTS public.license_events;
DROP TABLE IF EXISTS public.fastlane_events;
DROP TABLE IF EXISTS public.evidence_logs;
DROP TABLE IF EXISTS public.device_tokens;
DROP TABLE IF EXISTS public.device_audit_logs;
DROP TABLE IF EXISTS public.case_dossiers;
DROP TABLE IF EXISTS public.banned_users;
DROP TABLE IF EXISTS public.authz_revocations;
DROP TABLE IF EXISTS public.authz_requests;
DROP TABLE IF EXISTS public.authz_devices;
DROP TABLE IF EXISTS public.authz_decisions;
DROP TABLE IF EXISTS public.authz_credentials;
DROP TABLE IF EXISTS public.authz_audit_events;
DROP TABLE IF EXISTS public.authz_applications;
DROP TABLE IF EXISTS public.authz_actions;
DROP TABLE IF EXISTS public.app_categories;
DROP TABLE IF EXISTS public.allowed_apps;
DROP TABLE IF EXISTS public.alerts;
DROP TABLE IF EXISTS public.agent_health;
DROP TABLE IF EXISTS public.agent_configs;
DROP TABLE IF EXISTS public.admin_actions;
DROP TABLE IF EXISTS public.activity_logs;
DROP FUNCTION IF EXISTS public.users_due_for_backup();
DROP FUNCTION IF EXISTS public.update_updated_at_column();
DROP FUNCTION IF EXISTS public.run_retention_prune();
DROP FUNCTION IF EXISTS public.prune_evidence_objects(p_retention_days integer);
DROP FUNCTION IF EXISTS public.prune_alert_related_data(p_retention_days integer);
DROP FUNCTION IF EXISTS public.notify_principal_on_critical();
DROP FUNCTION IF EXISTS public.lock_license(p_key_hash text);
DROP TABLE IF EXISTS public.licenses;
DROP FUNCTION IF EXISTS public.has_role(_user_id uuid, _role public.app_role);
DROP FUNCTION IF EXISTS public.has_any_role(_user_id uuid, _roles public.app_role[]);
DROP FUNCTION IF EXISTS public.handle_new_user();
DROP FUNCTION IF EXISTS public.claim_telegram_phone(p_user_id uuid, p_telegram_chat_id bigint, p_phone text, p_ip_address text);
DROP FUNCTION IF EXISTS public.check_unauthorized_window_active();
DROP FUNCTION IF EXISTS public.authz_touch_updated_at();
DROP FUNCTION IF EXISTS public.activate_license_node(p_key_hash text, p_hardware_uuid text, p_hardware_fingerprint text, p_hostname text, p_auth_user_id uuid);
DROP TYPE IF EXISTS public.workstation_status;
DROP TYPE IF EXISTS public.unauthorized_event_kind;
DROP TYPE IF EXISTS public.authz_risk_level;
DROP TYPE IF EXISTS public.authz_request_status;
DROP TYPE IF EXISTS public.authz_device_status;
DROP TYPE IF EXISTS public.authz_decision;
DROP TYPE IF EXISTS public.app_role;
DROP TYPE IF EXISTS public.alert_severity;
DROP TYPE IF EXISTS public.admin_command;
DROP TYPE IF EXISTS public.action_status;
DROP SCHEMA IF EXISTS public;
--
-- Name: public; Type: SCHEMA; Schema: -; Owner: postgres
--

CREATE SCHEMA public;


ALTER SCHEMA public OWNER TO postgres;

--
-- Name: action_status; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.action_status AS ENUM (
    'pending',
    'sent',
    'acknowledged',
    'failed',
    'completed'
);


ALTER TYPE public.action_status OWNER TO postgres;

--
-- Name: admin_command; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.admin_command AS ENUM (
    'lock',
    'terminate',
    'freeze',
    'unfreeze',
    'kill_task',
    'set_alias'
);


ALTER TYPE public.admin_command OWNER TO postgres;

--
-- Name: alert_severity; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.alert_severity AS ENUM (
    'info',
    'warning',
    'critical',
    'high',
    'medium'
);


ALTER TYPE public.alert_severity OWNER TO postgres;

--
-- Name: app_role; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.app_role AS ENUM (
    'admin',
    'moderator',
    'user',
    'dev',
    'principal',
    'teacher',
    'helper'
);


ALTER TYPE public.app_role OWNER TO postgres;

--
-- Name: authz_decision; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.authz_decision AS ENUM (
    'ALLOW',
    'DENY',
    'APPROVAL_REQUIRED'
);


ALTER TYPE public.authz_decision OWNER TO postgres;

--
-- Name: authz_device_status; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.authz_device_status AS ENUM (
    'PENDING',
    'ACTIVE',
    'REVOKED',
    'EXPIRED'
);


ALTER TYPE public.authz_device_status OWNER TO postgres;

--
-- Name: authz_request_status; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.authz_request_status AS ENUM (
    'PENDING',
    'IDENTITY_SELECTED',
    'STEP_UP_REQUIRED',
    'STEP_UP_COMPLETE',
    'APPROVAL_REQUIRED',
    'APPROVED',
    'DENIED',
    'EXPIRED',
    'CONSUMED',
    'CANCELED'
);


ALTER TYPE public.authz_request_status OWNER TO postgres;

--
-- Name: authz_risk_level; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.authz_risk_level AS ENUM (
    'READ',
    'LOW_RISK_WRITE',
    'HIGH_RISK_WRITE',
    'DESTRUCTIVE',
    'SECURITY_CRITICAL'
);


ALTER TYPE public.authz_risk_level OWNER TO postgres;

--
-- Name: unauthorized_event_kind; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.unauthorized_event_kind AS ENUM (
    'unauthorized',
    'un-added'
);


ALTER TYPE public.unauthorized_event_kind OWNER TO postgres;

--
-- Name: workstation_status; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.workstation_status AS ENUM (
    'online',
    'offline'
);


ALTER TYPE public.workstation_status OWNER TO postgres;

--
-- Name: activate_license_node(text, text, text, text, uuid); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.activate_license_node(p_key_hash text, p_hardware_uuid text, p_hardware_fingerprint text, p_hostname text, p_auth_user_id uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_license record;
  v_existing_node record;
  v_active_count int;
  v_is_rebind boolean := false;
  v_node_id uuid;
BEGIN
  -- 1. Lock license
  SELECT * INTO v_license FROM public.licenses WHERE key_hash = p_key_hash FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error', 'invalid_key');
  END IF;

  IF v_license.status != 'active' THEN
    RETURN jsonb_build_object('error', 'status_' || v_license.status);
  END IF;

  IF current_timestamp > (v_license.expires_at + (v_license.grace_days || ' days')::interval) THEN
    RETURN jsonb_build_object('error', 'expired');
  END IF;

  -- 2. Find existing node
  SELECT * INTO v_existing_node FROM public.license_nodes 
  WHERE license_id = v_license.id 
    AND (hardware_uuid = p_hardware_uuid OR hardware_fingerprint = p_hardware_fingerprint)
  LIMIT 1;

  IF FOUND THEN
    IF v_existing_node.hardware_fingerprint != p_hardware_fingerprint OR v_existing_node.hardware_uuid != p_hardware_uuid THEN
      v_is_rebind := true;
    END IF;
  END IF;

  -- 3. Check limit if not an active existing node
  IF NOT FOUND OR v_existing_node.status != 'active' THEN
    SELECT count(*) INTO v_active_count FROM public.license_nodes 
    WHERE license_id = v_license.id AND status = 'active';

    IF v_active_count >= v_license.node_limit THEN
      INSERT INTO public.license_events (license_id, event_type, detail)
      VALUES (v_license.id, 'deny_limit', jsonb_build_object('hardware_uuid', p_hardware_uuid, 'hardware_fingerprint', p_hardware_fingerprint));
      RETURN jsonb_build_object('error', 'node_limit_reached', 'active_nodes', v_active_count, 'node_limit', v_license.node_limit);
    END IF;
  END IF;

  -- 4. Upsert Node
  IF v_existing_node.id IS NOT NULL THEN
    UPDATE public.license_nodes SET 
      hardware_uuid = p_hardware_uuid,
      hardware_fingerprint = p_hardware_fingerprint,
      hostname = COALESCE(p_hostname, hostname),
      status = 'active',
      last_seen_at = now(),
      auth_user_id = p_auth_user_id
    WHERE id = v_existing_node.id
    RETURNING id INTO v_node_id;
  ELSE
    INSERT INTO public.license_nodes (license_id, hardware_uuid, hardware_fingerprint, hostname, status, auth_user_id, last_seen_at)
    VALUES (v_license.id, p_hardware_uuid, p_hardware_fingerprint, p_hostname, 'active', p_auth_user_id, now())
    RETURNING id INTO v_node_id;
  END IF;

  -- 5. Upsert Workstation
  INSERT INTO public.workstations (id, name, status, last_heartbeat)
  VALUES (v_node_id, COALESCE(p_hostname, 'Unknown'), 'offline', now())
  ON CONFLICT (id) DO UPDATE SET 
    name = EXCLUDED.name;

  -- 6. Log event
  INSERT INTO public.license_events (license_id, node_id, event_type, detail)
  VALUES (v_license.id, v_node_id, CASE WHEN v_is_rebind THEN 'rebind' ELSE 'activate' END, jsonb_build_object('hardware_uuid', p_hardware_uuid, 'hardware_fingerprint', p_hardware_fingerprint, 'hostname', p_hostname));

  -- 7. Return success payload details
  RETURN jsonb_build_object(
    'success', true,
    'license_id', v_license.id,
    'node_id', v_node_id,
    'expires_at', v_license.expires_at,
    'grace_days', v_license.grace_days
  );
END;
$$;


ALTER FUNCTION public.activate_license_node(p_key_hash text, p_hardware_uuid text, p_hardware_fingerprint text, p_hostname text, p_auth_user_id uuid) OWNER TO postgres;

--
-- Name: authz_touch_updated_at(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.authz_touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
begin
  new.updated_at = now();
  return new;
end;
$$;


ALTER FUNCTION public.authz_touch_updated_at() OWNER TO postgres;

--
-- Name: check_unauthorized_window_active(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.check_unauthorized_window_active() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_is_active BOOLEAN;
BEGIN
  -- Check if there is an active class session window right now
  SELECT (now() >= start_at AND now() <= end_at) INTO v_is_active
  FROM public.unauthorized_window_settings
  WHERE id = 1;

  -- If class hasn't started or is over, silently ignore the incoming event update/insert
  IF v_is_active IS NOT TRUE THEN
    RETURN NULL; 
  END IF;

  -- Otherwise, allow the event to be logged
  RETURN NEW;
END;
$$;


ALTER FUNCTION public.check_unauthorized_window_active() OWNER TO postgres;

--
-- Name: claim_telegram_phone(uuid, bigint, text, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.claim_telegram_phone(p_user_id uuid, p_telegram_chat_id bigint, p_phone text, p_ip_address text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_session_user_id uuid;
    v_session_id uuid;
    v_expires_at timestamptz;
    v_profile_user_id uuid;
    v_phone_owner_user_id uuid;
    v_phone text;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'telegram_link_session_not_found';
    END IF;

    IF p_telegram_chat_id IS NULL THEN
        RAISE EXCEPTION 'telegram_link_session_not_found';
    END IF;

    v_phone := NULLIF(trim(p_phone), '');
    IF v_phone IS NULL THEN
        RAISE EXCEPTION 'Invalid phone number';
    END IF;

    -- Serialize concurrent attempts for the same Telegram identity and phone.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('oby:telegram:' || p_telegram_chat_id::text, 0)
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended('oby:phone:' || v_phone, 0)
    );

    SELECT id, user_id, expires_at
    INTO v_session_id, v_session_user_id, v_expires_at
    FROM public.phone_otp_sessions
    WHERE telegram_chat_id = p_telegram_chat_id
      AND purpose = 'telegram_link'
    FOR UPDATE;

    IF NOT FOUND OR v_session_user_id <> p_user_id THEN
        RAISE EXCEPTION 'telegram_link_session_not_found';
    END IF;

    IF v_expires_at IS NOT NULL AND v_expires_at <= now() THEN
        DELETE FROM public.phone_otp_sessions
        WHERE id = v_session_id;
        RAISE EXCEPTION 'telegram_link_session_not_found';
    END IF;

    -- A verified Telegram identity can belong to exactly one Obylon account.
    SELECT user_id
    INTO v_profile_user_id
    FROM public.profiles
    WHERE telegram_chat_id = p_telegram_chat_id
      AND phone_verified = TRUE
    FOR UPDATE;

    IF FOUND AND v_profile_user_id <> p_user_id THEN
        RAISE EXCEPTION 'telegram_already_linked';
    END IF;

    -- A verified phone number can belong to exactly one Obylon account.
    SELECT user_id
    INTO v_phone_owner_user_id
    FROM public.profiles
    WHERE phone = v_phone
      AND phone_verified = TRUE
    FOR UPDATE;

    IF FOUND AND v_phone_owner_user_id <> p_user_id THEN
        RAISE EXCEPTION 'phone_already_linked';
    END IF;

    -- Preserve the existing profile row when present; create it when the
    -- invite account has not created one yet.
    INSERT INTO public.profiles (
        user_id,
        phone,
        phone_verified,
        telegram_chat_id
    )
    VALUES (
        p_user_id,
        v_phone,
        TRUE,
        p_telegram_chat_id
    )
    ON CONFLICT (user_id)
    DO UPDATE SET
        phone = EXCLUDED.phone,
        phone_verified = TRUE,
        telegram_chat_id = EXCLUDED.telegram_chat_id;

    DELETE FROM public.phone_otp_sessions
    WHERE id = v_session_id;

    INSERT INTO public.security_audit_logs (
        user_id,
        event_type,
        status,
        ip_address
    )
    VALUES (
        p_user_id,
        'Phone number linked successfully',
        'success',
        p_ip_address
    );

    RETURN jsonb_build_object(
        'success', TRUE,
        'user_id', p_user_id,
        'telegram_chat_id', p_telegram_chat_id
    );
END;
$$;


ALTER FUNCTION public.claim_telegram_phone(p_user_id uuid, p_telegram_chat_id bigint, p_phone text, p_ip_address text) OWNER TO postgres;

--
-- Name: handle_new_user(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.handle_new_user() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
  INSERT INTO public.profiles (user_id, email, display_name)
  VALUES (NEW.id, NEW.email, COALESCE(NEW.raw_user_meta_data->>'display_name', split_part(NEW.email, '@', 1)));
  RETURN NEW;
END;
$$;


ALTER FUNCTION public.handle_new_user() OWNER TO postgres;

--
-- Name: has_any_role(uuid, public.app_role[]); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.has_any_role(_user_id uuid, _roles public.app_role[]) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.user_roles
    WHERE user_id = _user_id AND role = ANY(_roles)
  )
$$;


ALTER FUNCTION public.has_any_role(_user_id uuid, _roles public.app_role[]) OWNER TO postgres;

--
-- Name: has_role(uuid, public.app_role); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.has_role(_user_id uuid, _role public.app_role) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.user_roles
    WHERE user_id = _user_id
      AND (
        role = _role
        OR (_role = 'admin'::public.app_role
            AND role IN ('admin'::public.app_role,'dev'::public.app_role,'principal'::public.app_role))
      )
  )
$$;


ALTER FUNCTION public.has_role(_user_id uuid, _role public.app_role) OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: licenses; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.licenses (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    school_id uuid,
    key_hash text NOT NULL,
    plan_tier text DEFAULT 'standard'::text NOT NULL,
    node_limit integer DEFAULT 20 NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    grace_days integer DEFAULT 14 NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    school_name text,
    updated_at timestamp with time zone DEFAULT now(),
    key_prefix text,
    license_key text,
    CONSTRAINT licenses_status_check CHECK ((status = ANY (ARRAY['active'::text, 'suspended'::text, 'revoked'::text])))
);


ALTER TABLE public.licenses OWNER TO postgres;

--
-- Name: lock_license(text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.lock_license(p_key_hash text) RETURNS SETOF public.licenses
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM public.licenses
  WHERE key_hash = p_key_hash
  FOR UPDATE;
END;
$$;


ALTER FUNCTION public.lock_license(p_key_hash text) OWNER TO postgres;

--
-- Name: notify_principal_on_critical(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.notify_principal_on_critical() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'extensions'
    AS $$
declare
  fn_url text := 'https://mbelumnusmqpodjokqox.supabase.co/functions/v1/notify-principal';
  shared_secret text;
begin
  begin
    shared_secret := current_setting('app.gavel_secret', true);
  exception when others then
    shared_secret := null;
  end;

  perform net.http_post(
    url := fn_url,
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'x-gavel-secret', coalesce(shared_secret, '')
    ),
    body := jsonb_build_object(
      'alert_id', new.id,
      'workstation_id', new.workstation_id
    )
  );
  return new;
end;
$$;


ALTER FUNCTION public.notify_principal_on_critical() OWNER TO postgres;

--
-- Name: prune_alert_related_data(integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.prune_alert_related_data(p_retention_days integer DEFAULT 30) RETURNS TABLE(alerts_deleted bigint, evidence_deleted bigint, case_dossiers_deleted bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
declare
  v_cutoff timestamptz := now() - (p_retention_days || ' days')::interval;
  v_alerts_deleted bigint := 0;
  v_evidence_deleted bigint := 0;
  v_cases_deleted bigint := 0;
begin
  -- Delete dependent rows first
  with expired_alerts as (
    select id
    from public.alerts
    where "timestamp" < v_cutoff
  )
  delete from public.evidence_logs el
  using expired_alerts ea
  where el.alert_id = ea.id;

  get diagnostics v_evidence_deleted = row_count;

  with expired_alerts as (
    select id
    from public.alerts
    where "timestamp" < v_cutoff
  )
  delete from public.case_dossiers cd
  using expired_alerts ea
  where cd.alert_id = ea.id;

  get diagnostics v_cases_deleted = row_count;

  delete from public.alerts a
  where a."timestamp" < v_cutoff;

  get diagnostics v_alerts_deleted = row_count;

  return query
  select v_alerts_deleted, v_evidence_deleted, v_cases_deleted;
end;
$$;


ALTER FUNCTION public.prune_alert_related_data(p_retention_days integer) OWNER TO postgres;

--
-- Name: prune_evidence_objects(integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.prune_evidence_objects(p_retention_days integer DEFAULT 30) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
declare
  v_deleted bigint := 0;
begin
  delete from storage.objects o
  where o.bucket_id = 'evidence'
    and o.created_at < now() - (p_retention_days || ' days')::interval
  returning 1 into v_deleted;

  get diagnostics v_deleted = row_count;
  return v_deleted;
end;
$$;


ALTER FUNCTION public.prune_evidence_objects(p_retention_days integer) OWNER TO postgres;

--
-- Name: reclaim_license_node_on_workstation_delete(); Type: FUNCTION; Schema: public; Owner: postgres
--
-- BUGFIX (2026-09): workstations and license_nodes share the same id by
-- convention (see activate_license_node() above) but had no FK and
-- nothing kept them in sync — deleting a workstation (the dashboard's
-- "remove device" action) left its license_nodes row 'active' forever,
-- so the agent's license check never noticed and the seat was never
-- freed for a replacement machine. See db_license_node_reclaim_fix.sql
-- for the full writeup.
--

CREATE FUNCTION public.reclaim_license_node_on_workstation_delete() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_node record;
BEGIN
  SELECT * INTO v_node FROM public.license_nodes WHERE id = OLD.id;

  IF FOUND AND v_node.status = 'active' THEN
    UPDATE public.license_nodes
    SET status = 'reclaimed', last_seen_at = now()
    WHERE id = OLD.id;

    INSERT INTO public.license_events (license_id, node_id, event_type, detail)
    VALUES (
      v_node.license_id,
      v_node.id,
      'reclaim',
      jsonb_build_object(
        'reason', 'workstation_deleted',
        'hardware_uuid', v_node.hardware_uuid,
        'hostname', v_node.hostname
      )
    );
  END IF;

  RETURN OLD;
END;
$$;


ALTER FUNCTION public.reclaim_license_node_on_workstation_delete() OWNER TO postgres;

--
-- Name: run_retention_prune(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.run_retention_prune() RETURNS TABLE(audits_deleted bigint, cases_deleted bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
                  DECLARE
                    v_audits BIGINT := 0;
                      v_extra  BIGINT := 0;
                        v_cases  BIGINT := 0;
                        BEGIN
                          WITH del AS (
                              DELETE FROM public.security_audit_logs a
                                  USING public.user_preferences p
                                      WHERE a.user_id = p.user_id
                                            AND a.created_at < now() - (COALESCE(p.audit_retention_days, 30) || ' days')::interval
                                                RETURNING 1
                                                  )
                                                    SELECT count(*) INTO v_audits FROM del;

                                                      WITH del2 AS (
                                                          DELETE FROM public.security_audit_logs a
                                                              WHERE NOT EXISTS (SELECT 1 FROM public.user_preferences p WHERE p.user_id = a.user_id)
                                                                    AND a.created_at < now() - INTERVAL '30 days'
                                                                        RETURNING 1
                                                                          )
                                                                            SELECT count(*) INTO v_extra FROM del2;

                                                                              WITH del3 AS (
                                                                                  DELETE FROM public.case_dossiers
                                                                                      WHERE created_at < now() - INTERVAL '30 days'
                                                                                          RETURNING 1
                                                                                            )
                                                                                              SELECT count(*) INTO v_cases FROM del3;

                                                                                                UPDATE public.user_preferences SET last_prune_at = now();

                                                                                                  RETURN QUERY SELECT (v_audits + v_extra), v_cases;
                                                                                                  END;
                                                                                                  $$;


ALTER FUNCTION public.run_retention_prune() OWNER TO postgres;

--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public'
    AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;


ALTER FUNCTION public.update_updated_at_column() OWNER TO postgres;

--
-- Name: users_due_for_backup(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.users_due_for_backup() RETURNS TABLE(user_id uuid, backup_frequency text, telegram_chat_id text)
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
                                                                                                    SELECT p.user_id,
                                                                                                             p.backup_frequency,
                                                                                                                      pr.telegram_chat_id::TEXT
                                                                                                                          FROM public.user_preferences p
                                                                                                                              JOIN public.profiles pr ON pr.user_id = p.user_id
                                                                                                                                 WHERE p.auto_backup_enabled = true
                                                                                                                                      AND pr.telegram_chat_id IS NOT NULL
                                                                                                                                           AND (
                                                                                                                                                  p.last_backup_at IS NULL
                                                                                                                                                         OR p.last_backup_at < now() - (
                                                                                                                                                                  CASE p.backup_frequency
                                                                                                                                                                             WHEN 'daily'   THEN INTERVAL '1 day'
                                                                                                                                                                                        WHEN 'weekly'  THEN INTERVAL '7 days'
                                                                                                                                                                                                   WHEN 'monthly' THEN INTERVAL '30 days'
                                                                                                                                                                                                              ELSE INTERVAL '30 days'
                                                                                                                                                                                                                       END
                                                                                                                                                                                                                                - INTERVAL '1 hour'
                                                                                                                                                                                                                                       )
                                                                                                                                                                                                                                            );
                                                                                                                                                                                                                                            $$;


ALTER FUNCTION public.users_due_for_backup() OWNER TO postgres;

--
-- Name: activity_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.activity_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workstation_id uuid,
    process_name text,
    window_title text,
    severity text DEFAULT 'info'::text NOT NULL,
    is_anomaly boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_backlogged boolean DEFAULT false,
    CONSTRAINT activity_logs_severity_check CHECK ((severity = ANY (ARRAY['info'::text, 'warning'::text])))
);


ALTER TABLE public.activity_logs OWNER TO postgres;

--
-- Name: admin_actions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.admin_actions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    command public.admin_command NOT NULL,
    target_id uuid,
    status public.action_status DEFAULT 'pending'::public.action_status NOT NULL,
    issued_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    metadata jsonb
);


ALTER TABLE public.admin_actions OWNER TO postgres;

--
-- Name: agent_configs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_configs (
    workstation_id uuid NOT NULL,
    log_only_mode boolean DEFAULT false,
    focus_mode boolean DEFAULT false,
    monitoring_interval integer DEFAULT 5,
    sync_interval integer DEFAULT 60,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    strict_warden boolean DEFAULT false,
    usb_execution_policy integer DEFAULT 0,
    exam_mode boolean DEFAULT false NOT NULL,
    exam_allowed_apps text[] DEFAULT ARRAY['chrome.exe'::text, 'msedge.exe'::text] NOT NULL,
    exam_freeze_duration integer DEFAULT 300 NOT NULL,
    kill_unauthorized_apps boolean DEFAULT false NOT NULL,
    webcam_evidence_enabled boolean DEFAULT true NOT NULL
);


ALTER TABLE public.agent_configs OWNER TO postgres;

--
-- Name: agent_health; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_health (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workstation_id text,
    status text NOT NULL,
    error_log text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.agent_health OWNER TO postgres;

--
-- Name: alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alerts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workstation_id uuid,
    process_name text,
    window_title text,
    severity public.alert_severity DEFAULT 'info'::public.alert_severity NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    action_taken text,
    resolved boolean DEFAULT false,
    resolved_at timestamp with time zone,
    is_backlogged boolean DEFAULT false,
    alert_type text
);


ALTER TABLE public.alerts OWNER TO postgres;

--
-- Name: allowed_apps; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.allowed_apps (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    process_name text NOT NULL,
    category text,
    icon text,
    whitelisted boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.allowed_apps OWNER TO postgres;

--
-- Name: app_categories; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.app_categories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.app_categories OWNER TO postgres;

--
-- Name: authz_actions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authz_actions (
    action_id text NOT NULL,
    application_id uuid NOT NULL,
    display_name text NOT NULL,
    description text,
    risk_level public.authz_risk_level NOT NULL,
    required_scope text NOT NULL,
    minimum_role text,
    approval_policy text DEFAULT 'NONE'::text NOT NULL,
    target_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.authz_actions OWNER TO postgres;

--
-- Name: TABLE authz_actions; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.authz_actions IS 'Central action registry used by server-side authorization policy.';


--
-- Name: authz_applications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authz_applications (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    slug text NOT NULL,
    display_name text NOT NULL,
    description text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.authz_applications OWNER TO postgres;

--
-- Name: authz_audit_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authz_audit_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_type text NOT NULL,
    request_id uuid,
    credential_id uuid,
    device_id uuid,
    application_id uuid,
    actor_user_id uuid,
    actor_identity_id uuid,
    action_id text,
    decision public.authz_decision,
    risk_level public.authz_risk_level,
    target jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.authz_audit_events OWNER TO postgres;

--
-- Name: TABLE authz_audit_events; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.authz_audit_events IS 'Durable audit trail; never store raw bearer tokens or private keys.';


--
-- Name: authz_credentials; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authz_credentials (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    request_id uuid,
    application_id uuid NOT NULL,
    device_id uuid NOT NULL,
    identity_id uuid,
    issued_to_user_id uuid,
    access_token_hash text NOT NULL,
    refresh_token_hash text,
    token_jti text,
    scopes text[] DEFAULT '{}'::text[] NOT NULL,
    action_id text,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


ALTER TABLE public.authz_credentials OWNER TO postgres;

--
-- Name: TABLE authz_credentials; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.authz_credentials IS 'Client-specific, scoped, expiring authorization credentials. Raw tokens must not be stored.';


--
-- Name: authz_decisions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authz_decisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    request_id uuid NOT NULL,
    action_id text NOT NULL,
    device_id uuid,
    identity_id uuid,
    decided_by_user_id uuid,
    decided_by_identity_id uuid,
    decision public.authz_decision NOT NULL,
    reason text,
    policy_version text,
    target_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT authz_decisions_target_matches_request CHECK ((jsonb_typeof(target_snapshot) = 'object'::text))
);


ALTER TABLE public.authz_decisions OWNER TO postgres;

--
-- Name: authz_devices; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authz_devices (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    application_id uuid NOT NULL,
    device_fingerprint text NOT NULL,
    device_name text,
    platform text,
    status public.authz_device_status DEFAULT 'PENDING'::public.authz_device_status NOT NULL,
    public_key text,
    authorized_identity_id uuid,
    authorized_by_user_id uuid,
    authorized_at timestamp with time zone,
    revoked_at timestamp with time zone,
    last_seen_at timestamp with time zone,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.authz_devices OWNER TO postgres;

--
-- Name: authz_requests; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authz_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    application_id uuid NOT NULL,
    device_id uuid,
    device_code_hash text NOT NULL,
    user_code_hash text NOT NULL,
    verification_uri text,
    verification_uri_complete text,
    action_id text NOT NULL,
    requested_scopes text[] DEFAULT '{}'::text[] NOT NULL,
    granted_scopes text[] DEFAULT '{}'::text[] NOT NULL,
    target jsonb DEFAULT '{}'::jsonb NOT NULL,
    status public.authz_request_status DEFAULT 'PENDING'::public.authz_request_status NOT NULL,
    selected_identity_id uuid,
    requesting_user_id uuid,
    selected_at timestamp with time zone,
    step_up_required boolean DEFAULT false NOT NULL,
    step_up_completed_at timestamp with time zone,
    approved_by_user_id uuid,
    approved_by_identity_id uuid,
    approved_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    canceled_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT authz_no_self_identity_approval CHECK (((selected_identity_id IS NULL) OR (approved_by_identity_id IS NULL) OR (selected_identity_id <> approved_by_identity_id)))
);


ALTER TABLE public.authz_requests OWNER TO postgres;

--
-- Name: TABLE authz_requests; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.authz_requests IS 'Short-lived browser-mediated authorization requests for Umbraxis clients.';


--
-- Name: authz_revocations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.authz_revocations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    credential_id uuid,
    device_id uuid,
    identity_id uuid,
    revoked_by_user_id uuid,
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone
);


ALTER TABLE public.authz_revocations OWNER TO postgres;

--
-- Name: banned_users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.banned_users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    banned_by uuid,
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.banned_users OWNER TO postgres;

--
-- Name: case_dossiers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.case_dossiers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workstation_id uuid NOT NULL,
    alert_id uuid,
    student_name text NOT NULL,
    student_class text,
    student_section text,
    remarks text,
    ai_summary text NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now(),
    resolved boolean DEFAULT false,
    status text DEFAULT 'open'::text,
    metadata jsonb,
    timeline jsonb,
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.case_dossiers OWNER TO postgres;

--
-- Name: device_audit_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device_audit_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    event_type text NOT NULL,
    pairing_session_id uuid,
    linked_device_id uuid,
    ip inet,
    user_agent text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT device_audit_logs_event_type_check CHECK ((event_type = ANY (ARRAY['pair_session_created'::text, 'qr_scanned'::text, 'approval_requested'::text, 'pair_approved'::text, 'pair_rejected'::text, 'pair_expired'::text, 'pair_cancelled'::text, 'device_revoked'::text, 'device_renamed'::text, 'login_via_pair'::text, 'token_refreshed'::text])))
);


ALTER TABLE public.device_audit_logs OWNER TO postgres;

--
-- Name: device_tokens; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid,
    token text NOT NULL,
    platform text DEFAULT 'android'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.device_tokens OWNER TO postgres;

--
-- Name: evidence_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.evidence_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    alert_id uuid,
    screenshot_url text,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    webcam_url text
);


ALTER TABLE public.evidence_logs OWNER TO postgres;

--
-- Name: fastlane_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.fastlane_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workstation_id text NOT NULL,
    type text NOT NULL,
    kind text NOT NULL,
    detail text,
    action_taken text,
    screenshot_path text,
    "timestamp" bigint NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.fastlane_events OWNER TO postgres;

--
-- Name: license_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.license_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    license_id uuid NOT NULL,
    node_id uuid,
    event_type text NOT NULL,
    detail jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT license_events_event_type_check CHECK ((event_type = ANY (ARRAY['activate'::text, 'deny_limit'::text, 'rebind'::text, 'deactivate'::text, 'reclaim'::text, 'revoke'::text, 'renew'::text])))
);


ALTER TABLE public.license_events OWNER TO postgres;

--
-- Name: license_nodes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.license_nodes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    license_id uuid NOT NULL,
    hardware_uuid text NOT NULL,
    hardware_fingerprint text NOT NULL,
    hostname text,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    auth_user_id uuid,
    CONSTRAINT license_nodes_status_check CHECK ((status = ANY (ARRAY['active'::text, 'deactivated'::text, 'reclaimed'::text])))
);


ALTER TABLE public.license_nodes OWNER TO postgres;

--
-- Name: linked_devices; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.linked_devices (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    pairing_session_id uuid,
    device_name text DEFAULT 'Unknown Device'::text NOT NULL,
    browser text,
    os text,
    platform text,
    ip inet,
    location text,
    fingerprint text,
    trust_level text DEFAULT 'standard'::text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    first_paired_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone,
    CONSTRAINT linked_devices_trust_level_check CHECK ((trust_level = ANY (ARRAY['standard'::text, 'elevated'::text, 'restricted'::text])))
);


ALTER TABLE public.linked_devices OWNER TO postgres;

--
-- Name: pairing_sessions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.pairing_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    token text DEFAULT encode(extensions.gen_random_bytes(32), 'hex'::text) NOT NULL,
    initiator_id uuid,
    desktop_browser text,
    desktop_os text,
    desktop_device_name text,
    desktop_ip inet,
    desktop_location text,
    desktop_fingerprint text,
    status text DEFAULT 'waiting'::text NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '00:01:00'::interval) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    consumed_at timestamp with time zone,
    code text,
    auth_token_hash text,
    CONSTRAINT pairing_sessions_status_check CHECK ((status = ANY (ARRAY['waiting'::text, 'scanned'::text, 'approved'::text, 'rejected'::text, 'expired'::text, 'cancelled'::text])))
);


ALTER TABLE public.pairing_sessions OWNER TO postgres;

--
-- Name: phone_otp_sessions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.phone_otp_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    phone text,
    otp_code text,
    telegram_chat_id bigint,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    purpose text DEFAULT 'telegram_link'::text NOT NULL,
    token_hash text,
    telegram_user_id bigint
);


ALTER TABLE public.phone_otp_sessions OWNER TO postgres;

--
-- Name: phone_otp_sessions_obylon_pre_fix; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.phone_otp_sessions_obylon_pre_fix (
    id uuid,
    user_id uuid,
    phone text,
    otp_code text,
    telegram_chat_id bigint,
    expires_at timestamp with time zone,
    created_at timestamp with time zone
);


ALTER TABLE public.phone_otp_sessions_obylon_pre_fix OWNER TO postgres;

--
-- Name: phone_otp_sessions_obylon_pre_fix_v2; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.phone_otp_sessions_obylon_pre_fix_v2 (
    id uuid,
    user_id uuid,
    phone text,
    otp_code text,
    telegram_chat_id bigint,
    expires_at timestamp with time zone,
    created_at timestamp with time zone,
    purpose text
);


ALTER TABLE public.phone_otp_sessions_obylon_pre_fix_v2 OWNER TO postgres;

--
-- Name: profiles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.profiles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    display_name text,
    email text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    phone text,
    phone_verified boolean DEFAULT false,
    telegram_chat_id bigint,
    is_banned boolean DEFAULT false,
    first_name text,
    last_name text,
    username text,
    avatar_url text
);


ALTER TABLE public.profiles OWNER TO postgres;

--
-- Name: profiles_obylon_pre_fix; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.profiles_obylon_pre_fix (
    id uuid,
    user_id uuid,
    display_name text,
    email text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    phone text,
    phone_verified boolean,
    telegram_chat_id bigint,
    is_banned boolean,
    first_name text,
    last_name text,
    username text,
    avatar_url text
);


ALTER TABLE public.profiles_obylon_pre_fix OWNER TO postgres;

--
-- Name: profiles_obylon_pre_fix_v2; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.profiles_obylon_pre_fix_v2 (
    id uuid,
    user_id uuid,
    display_name text,
    email text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    phone text,
    phone_verified boolean,
    telegram_chat_id bigint,
    is_banned boolean,
    first_name text,
    last_name text,
    username text,
    avatar_url text
);


ALTER TABLE public.profiles_obylon_pre_fix_v2 OWNER TO postgres;

--
-- Name: security_audit_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.security_audit_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    event_type text NOT NULL,
    ip_address text,
    status text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.security_audit_logs OWNER TO postgres;

--
-- Name: system_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.system_settings (
    id integer DEFAULT 1 NOT NULL,
    focus_mode boolean DEFAULT false NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT singleton CHECK ((id = 1))
);


ALTER TABLE public.system_settings OWNER TO postgres;

--
-- Name: unauthorized_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.unauthorized_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    workstation_id uuid NOT NULL,
    process_name text NOT NULL,
    window_title text,
    payload text,
    kind public.unauthorized_event_kind DEFAULT 'unauthorized'::public.unauthorized_event_kind NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    last_seen timestamp with time zone DEFAULT now() NOT NULL,
    duration_seconds integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.unauthorized_events OWNER TO postgres;

--
-- Name: unauthorized_window_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.unauthorized_window_settings (
    id integer DEFAULT 1 NOT NULL,
    start_at timestamp with time zone NOT NULL,
    end_at timestamp with time zone NOT NULL,
    clear_at timestamp with time zone NOT NULL,
    clear_delay_seconds integer DEFAULT 1800 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    started_by_id uuid,
    started_by_name text,
    started_by_role text,
    CONSTRAINT clear_after_end CHECK ((clear_at >= end_at)),
    CONSTRAINT end_after_start CHECK ((end_at > start_at)),
    CONSTRAINT unauthorized_window_settings_id_check CHECK ((id = 1))
);


ALTER TABLE public.unauthorized_window_settings OWNER TO postgres;

--
-- Name: unban_requests; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.unban_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    reason text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    resolved_by uuid,
    CONSTRAINT unban_requests_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text])))
);


ALTER TABLE public.unban_requests OWNER TO postgres;

--
-- Name: user_preferences; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_preferences (
    user_id uuid NOT NULL,
    email_critical_alerts boolean DEFAULT true,
    email_hardware_panic boolean DEFAULT false,
    email_new_logins boolean DEFAULT true,
    updated_at timestamp with time zone DEFAULT now(),
    audit_retention_days integer DEFAULT 30,
    auto_backup_enabled boolean DEFAULT false,
    backup_frequency text DEFAULT 'monthly'::text NOT NULL,
    last_backup_at timestamp with time zone,
    last_prune_at timestamp with time zone,
    CONSTRAINT user_preferences_backup_frequency_check CHECK ((backup_frequency = ANY (ARRAY['daily'::text, 'weekly'::text, 'monthly'::text]))),
    CONSTRAINT user_preferences_retention_bounds_chk CHECK (((audit_retention_days IS NULL) OR ((audit_retention_days >= 1) AND (audit_retention_days <= 365))))
);


ALTER TABLE public.user_preferences OWNER TO postgres;

--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    role public.app_role NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.user_roles OWNER TO postgres;

--
-- Name: user_sessions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    session_id uuid,
    device_name text,
    browser text,
    ip_address text,
    location text,
    is_current boolean DEFAULT false,
    last_active_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    status text DEFAULT 'active'::text NOT NULL
);


ALTER TABLE public.user_sessions OWNER TO postgres;

--
-- Name: user_totp; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_totp (
    user_id uuid NOT NULL,
    secret text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    last_used_step bigint,
    verified_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.user_totp OWNER TO postgres;

--
-- Name: workstations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.workstations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    status public.workstation_status DEFAULT 'offline'::public.workstation_status NOT NULL,
    last_heartbeat timestamp with time zone,
    os_info jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    current_window text,
    current_process text,
    hardware_uuid text,
    owner_id uuid,
    role public.app_role,
    current_app text,
    alias_verified boolean DEFAULT false
);


ALTER TABLE public.workstations OWNER TO postgres;

--
-- Name: activity_logs activity_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_pkey PRIMARY KEY (id);


--
-- Name: admin_actions admin_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_actions
    ADD CONSTRAINT admin_actions_pkey PRIMARY KEY (id);


--
-- Name: agent_configs agent_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_configs
    ADD CONSTRAINT agent_configs_pkey PRIMARY KEY (workstation_id);


--
-- Name: agent_health agent_health_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_health
    ADD CONSTRAINT agent_health_pkey PRIMARY KEY (id);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);


--
-- Name: allowed_apps allowed_apps_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.allowed_apps
    ADD CONSTRAINT allowed_apps_pkey PRIMARY KEY (id);


--
-- Name: allowed_apps allowed_apps_process_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.allowed_apps
    ADD CONSTRAINT allowed_apps_process_name_key UNIQUE (process_name);


--
-- Name: app_categories app_categories_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.app_categories
    ADD CONSTRAINT app_categories_name_key UNIQUE (name);


--
-- Name: app_categories app_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.app_categories
    ADD CONSTRAINT app_categories_pkey PRIMARY KEY (id);


--
-- Name: authz_actions authz_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_actions
    ADD CONSTRAINT authz_actions_pkey PRIMARY KEY (action_id);


--
-- Name: authz_applications authz_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_applications
    ADD CONSTRAINT authz_applications_pkey PRIMARY KEY (id);


--
-- Name: authz_applications authz_applications_slug_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_applications
    ADD CONSTRAINT authz_applications_slug_key UNIQUE (slug);


--
-- Name: authz_audit_events authz_audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_audit_events
    ADD CONSTRAINT authz_audit_events_pkey PRIMARY KEY (id);


--
-- Name: authz_credentials authz_credentials_access_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_credentials
    ADD CONSTRAINT authz_credentials_access_token_hash_key UNIQUE (access_token_hash);


--
-- Name: authz_credentials authz_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_credentials
    ADD CONSTRAINT authz_credentials_pkey PRIMARY KEY (id);


--
-- Name: authz_credentials authz_credentials_token_jti_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_credentials
    ADD CONSTRAINT authz_credentials_token_jti_key UNIQUE (token_jti);


--
-- Name: authz_decisions authz_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_decisions
    ADD CONSTRAINT authz_decisions_pkey PRIMARY KEY (id);


--
-- Name: authz_devices authz_devices_application_id_device_fingerprint_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_devices
    ADD CONSTRAINT authz_devices_application_id_device_fingerprint_key UNIQUE (application_id, device_fingerprint);


--
-- Name: authz_devices authz_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_devices
    ADD CONSTRAINT authz_devices_pkey PRIMARY KEY (id);


--
-- Name: authz_requests authz_requests_device_code_hash_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_requests
    ADD CONSTRAINT authz_requests_device_code_hash_key UNIQUE (device_code_hash);


--
-- Name: authz_requests authz_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_requests
    ADD CONSTRAINT authz_requests_pkey PRIMARY KEY (id);


--
-- Name: authz_requests authz_requests_user_code_hash_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_requests
    ADD CONSTRAINT authz_requests_user_code_hash_key UNIQUE (user_code_hash);


--
-- Name: authz_revocations authz_revocations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_revocations
    ADD CONSTRAINT authz_revocations_pkey PRIMARY KEY (id);


--
-- Name: banned_users banned_users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.banned_users
    ADD CONSTRAINT banned_users_pkey PRIMARY KEY (id);


--
-- Name: case_dossiers case_dossiers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.case_dossiers
    ADD CONSTRAINT case_dossiers_pkey PRIMARY KEY (id);


--
-- Name: device_audit_logs device_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_audit_logs
    ADD CONSTRAINT device_audit_logs_pkey PRIMARY KEY (id);


--
-- Name: device_tokens device_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_tokens
    ADD CONSTRAINT device_tokens_pkey PRIMARY KEY (id);


--
-- Name: device_tokens device_tokens_token_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_tokens
    ADD CONSTRAINT device_tokens_token_key UNIQUE (token);


--
-- Name: evidence_logs evidence_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evidence_logs
    ADD CONSTRAINT evidence_logs_pkey PRIMARY KEY (id);


--
-- Name: fastlane_events fastlane_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.fastlane_events
    ADD CONSTRAINT fastlane_events_pkey PRIMARY KEY (id);


--
-- Name: license_events license_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.license_events
    ADD CONSTRAINT license_events_pkey PRIMARY KEY (id);


--
-- Name: license_nodes license_nodes_license_id_hardware_uuid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.license_nodes
    ADD CONSTRAINT license_nodes_license_id_hardware_uuid_key UNIQUE (license_id, hardware_uuid);


--
-- Name: license_nodes license_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.license_nodes
    ADD CONSTRAINT license_nodes_pkey PRIMARY KEY (id);


--
-- Name: licenses licenses_key_hash_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_key_hash_key UNIQUE (key_hash);


--
-- Name: licenses licenses_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.licenses
    ADD CONSTRAINT licenses_pkey PRIMARY KEY (id);


--
-- Name: linked_devices linked_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.linked_devices
    ADD CONSTRAINT linked_devices_pkey PRIMARY KEY (id);


--
-- Name: pairing_sessions pairing_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pairing_sessions
    ADD CONSTRAINT pairing_sessions_pkey PRIMARY KEY (id);


--
-- Name: pairing_sessions pairing_sessions_token_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pairing_sessions
    ADD CONSTRAINT pairing_sessions_token_key UNIQUE (token);


--
-- Name: phone_otp_sessions phone_otp_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.phone_otp_sessions
    ADD CONSTRAINT phone_otp_sessions_pkey PRIMARY KEY (id);


--
-- Name: phone_otp_sessions phone_otp_sessions_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.phone_otp_sessions
    ADD CONSTRAINT phone_otp_sessions_user_id_key UNIQUE (user_id);


--
-- Name: profiles profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);


--
-- Name: profiles profiles_user_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_user_id_key UNIQUE (user_id);


--
-- Name: security_audit_logs security_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_audit_logs
    ADD CONSTRAINT security_audit_logs_pkey PRIMARY KEY (id);


--
-- Name: system_settings system_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (id);


--
-- Name: unauthorized_events unauthorized_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unauthorized_events
    ADD CONSTRAINT unauthorized_events_pkey PRIMARY KEY (id);


--
-- Name: unauthorized_window_settings unauthorized_window_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unauthorized_window_settings
    ADD CONSTRAINT unauthorized_window_settings_pkey PRIMARY KEY (id);


--
-- Name: unban_requests unban_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unban_requests
    ADD CONSTRAINT unban_requests_pkey PRIMARY KEY (id);


--
-- Name: user_preferences user_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (user_id);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (id);


--
-- Name: user_roles user_roles_user_id_role_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_role_key UNIQUE (user_id, role);


--
-- Name: user_sessions user_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_pkey PRIMARY KEY (id);


--
-- Name: user_totp user_totp_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_totp
    ADD CONSTRAINT user_totp_pkey PRIMARY KEY (user_id);


--
-- Name: workstations workstations_hardware_uuid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workstations
    ADD CONSTRAINT workstations_hardware_uuid_key UNIQUE (hardware_uuid);


--
-- Name: workstations workstations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workstations
    ADD CONSTRAINT workstations_pkey PRIMARY KEY (id);


--
-- Name: activity_logs_anomaly_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX activity_logs_anomaly_idx ON public.activity_logs USING btree (is_anomaly, created_at DESC) WHERE is_anomaly;


--
-- Name: activity_logs_ws_created_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX activity_logs_ws_created_idx ON public.activity_logs USING btree (workstation_id, created_at DESC);


--
-- Name: admin_actions_target_status_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX admin_actions_target_status_idx ON public.admin_actions USING btree (target_id, status, created_at DESC);


--
-- Name: authz_audit_events_actor_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_audit_events_actor_idx ON public.authz_audit_events USING btree (actor_user_id, created_at DESC);


--
-- Name: authz_audit_events_created_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_audit_events_created_idx ON public.authz_audit_events USING btree (created_at DESC);


--
-- Name: authz_audit_events_device_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_audit_events_device_idx ON public.authz_audit_events USING btree (device_id, created_at DESC);


--
-- Name: authz_credentials_active_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_credentials_active_idx ON public.authz_credentials USING btree (expires_at) WHERE (revoked_at IS NULL);


--
-- Name: authz_credentials_device_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_credentials_device_idx ON public.authz_credentials USING btree (device_id);


--
-- Name: authz_credentials_identity_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_credentials_identity_idx ON public.authz_credentials USING btree (identity_id);


--
-- Name: authz_decisions_request_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_decisions_request_idx ON public.authz_decisions USING btree (request_id, created_at DESC);


--
-- Name: authz_devices_identity_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_devices_identity_idx ON public.authz_devices USING btree (authorized_identity_id);


--
-- Name: authz_devices_status_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_devices_status_idx ON public.authz_devices USING btree (status);


--
-- Name: authz_requests_device_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_requests_device_idx ON public.authz_requests USING btree (device_id);


--
-- Name: authz_requests_identity_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_requests_identity_idx ON public.authz_requests USING btree (selected_identity_id);


--
-- Name: authz_requests_requesting_user_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_requests_requesting_user_idx ON public.authz_requests USING btree (requesting_user_id);


--
-- Name: authz_requests_status_expiry_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_requests_status_expiry_idx ON public.authz_requests USING btree (status, expires_at);


--
-- Name: authz_revocations_credential_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_revocations_credential_idx ON public.authz_revocations USING btree (credential_id);


--
-- Name: authz_revocations_device_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX authz_revocations_device_idx ON public.authz_revocations USING btree (device_id);


--
-- Name: device_tokens_user_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX device_tokens_user_idx ON public.device_tokens USING btree (user_id);


--
-- Name: fastlane_events_received_at_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX fastlane_events_received_at_idx ON public.fastlane_events USING btree (received_at DESC);


--
-- Name: fastlane_events_workstation_id_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX fastlane_events_workstation_id_idx ON public.fastlane_events USING btree (workstation_id);


--
-- Name: idx_alerts_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_timestamp ON public.alerts USING btree ("timestamp" DESC);


--
-- Name: idx_alerts_workstation; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_alerts_workstation ON public.alerts USING btree (workstation_id);


--
-- Name: idx_case_dossiers_workstation; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_case_dossiers_workstation ON public.case_dossiers USING btree (workstation_id);


--
-- Name: idx_device_audit_logs_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_device_audit_logs_user ON public.device_audit_logs USING btree (user_id, created_at DESC);


--
-- Name: idx_license_nodes_hardware_fingerprint; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_license_nodes_hardware_fingerprint ON public.license_nodes USING btree (hardware_fingerprint);


--
-- Name: idx_license_nodes_license_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_license_nodes_license_id ON public.license_nodes USING btree (license_id);


--
-- Name: idx_licenses_key_hash; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_licenses_key_hash ON public.licenses USING btree (key_hash);


--
-- Name: idx_linked_devices_user; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_linked_devices_user ON public.linked_devices USING btree (user_id, is_active);


--
-- Name: idx_pairing_sessions_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_pairing_sessions_code ON public.pairing_sessions USING btree (code) WHERE ((code IS NOT NULL) AND (status = ANY (ARRAY['waiting'::text, 'scanned'::text])));


--
-- Name: idx_pairing_sessions_expires; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_pairing_sessions_expires ON public.pairing_sessions USING btree (expires_at) WHERE (status = 'waiting'::text);


--
-- Name: idx_pairing_sessions_token; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_pairing_sessions_token ON public.pairing_sessions USING btree (token);


--
-- Name: idx_phone_otp_sessions_expires; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_phone_otp_sessions_expires ON public.phone_otp_sessions USING btree (expires_at);


--
-- Name: idx_phone_otp_sessions_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_phone_otp_sessions_user_id ON public.phone_otp_sessions USING btree (user_id);


--
-- Name: phone_otp_sessions_login_phone_uidx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX phone_otp_sessions_login_phone_uidx ON public.phone_otp_sessions USING btree (phone) WHERE ((purpose = 'login_otp'::text) AND (phone IS NOT NULL));


--
-- Name: phone_otp_sessions_telegram_link_chat_uidx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX phone_otp_sessions_telegram_link_chat_uidx ON public.phone_otp_sessions USING btree (telegram_chat_id) WHERE ((purpose = 'telegram_link'::text) AND (telegram_chat_id IS NOT NULL));


--
-- Name: phone_otp_sessions_telegram_lookup; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX phone_otp_sessions_telegram_lookup ON public.phone_otp_sessions USING btree (telegram_chat_id, telegram_user_id, purpose);


--
-- Name: phone_otp_sessions_token_hash_unique; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX phone_otp_sessions_token_hash_unique ON public.phone_otp_sessions USING btree (token_hash) WHERE (token_hash IS NOT NULL);


--
-- Name: phone_otp_sessions_user_purpose_uidx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX phone_otp_sessions_user_purpose_uidx ON public.phone_otp_sessions USING btree (user_id, purpose);


--
-- Name: phone_otp_sessions_user_purpose_unique; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX phone_otp_sessions_user_purpose_unique ON public.phone_otp_sessions USING btree (user_id, purpose);


--
-- Name: profiles_verified_phone_uidx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX profiles_verified_phone_uidx ON public.profiles USING btree (phone) WHERE ((phone_verified = true) AND (phone IS NOT NULL));


--
-- Name: profiles_verified_telegram_chat_uidx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX profiles_verified_telegram_chat_uidx ON public.profiles USING btree (telegram_chat_id) WHERE ((phone_verified = true) AND (telegram_chat_id IS NOT NULL));


--
-- Name: agent_configs agent_configs_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER agent_configs_updated BEFORE UPDATE ON public.agent_configs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: alerts alerts_critical_notify; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER alerts_critical_notify AFTER INSERT ON public.alerts FOR EACH ROW WHEN ((new.severity = 'critical'::public.alert_severity)) EXECUTE FUNCTION public.notify_principal_on_critical();


--
-- Name: allowed_apps allowed_apps_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER allowed_apps_updated BEFORE UPDATE ON public.allowed_apps FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: authz_actions authz_actions_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER authz_actions_updated_at BEFORE UPDATE ON public.authz_actions FOR EACH ROW EXECUTE FUNCTION public.authz_touch_updated_at();


--
-- Name: authz_applications authz_applications_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER authz_applications_updated_at BEFORE UPDATE ON public.authz_applications FOR EACH ROW EXECUTE FUNCTION public.authz_touch_updated_at();


--
-- Name: authz_devices authz_devices_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER authz_devices_updated_at BEFORE UPDATE ON public.authz_devices FOR EACH ROW EXECUTE FUNCTION public.authz_touch_updated_at();


--
-- Name: authz_requests authz_requests_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER authz_requests_updated_at BEFORE UPDATE ON public.authz_requests FOR EACH ROW EXECUTE FUNCTION public.authz_touch_updated_at();


--
-- Name: case_dossiers case_dossiers_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER case_dossiers_updated BEFORE UPDATE ON public.case_dossiers FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: unauthorized_events enforce_unauthorized_window_update; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER enforce_unauthorized_window_update BEFORE INSERT OR UPDATE ON public.unauthorized_events FOR EACH ROW EXECUTE FUNCTION public.check_unauthorized_window_active();


--
-- Name: profiles profiles_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER profiles_updated BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: system_settings system_settings_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER system_settings_updated BEFORE UPDATE ON public.system_settings FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: unauthorized_window_settings unauthorized_window_settings_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER unauthorized_window_settings_updated BEFORE UPDATE ON public.unauthorized_window_settings FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: workstations workstations_reclaim_license_node; Type: TRIGGER; Schema: public; Owner: postgres
--
-- BUGFIX (2026-09): see reclaim_license_node_on_workstation_delete() above
-- and db_license_node_reclaim_fix.sql — without this, deleting a
-- workstation (the dashboard's "remove device" action) never touched its
-- license_nodes row, so the agent kept running and the seat was never
-- freed.
--

CREATE TRIGGER workstations_reclaim_license_node AFTER DELETE ON public.workstations FOR EACH ROW EXECUTE FUNCTION public.reclaim_license_node_on_workstation_delete();


--
-- Name: workstations workstations_updated; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER workstations_updated BEFORE UPDATE ON public.workstations FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: activity_logs activity_logs_workstation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activity_logs
    ADD CONSTRAINT activity_logs_workstation_id_fkey FOREIGN KEY (workstation_id) REFERENCES public.workstations(id) ON DELETE CASCADE;


--
-- Name: admin_actions admin_actions_issued_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_actions
    ADD CONSTRAINT admin_actions_issued_by_fkey FOREIGN KEY (issued_by) REFERENCES auth.users(id);


--
-- Name: admin_actions admin_actions_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_actions
    ADD CONSTRAINT admin_actions_target_id_fkey FOREIGN KEY (target_id) REFERENCES public.workstations(id) ON DELETE CASCADE;


--
-- Name: agent_configs agent_configs_workstation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_configs
    ADD CONSTRAINT agent_configs_workstation_id_fkey FOREIGN KEY (workstation_id) REFERENCES public.workstations(id) ON DELETE CASCADE;


--
-- Name: alerts alerts_workstation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_workstation_id_fkey FOREIGN KEY (workstation_id) REFERENCES public.workstations(id) ON DELETE CASCADE;


--
-- Name: authz_actions authz_actions_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_actions
    ADD CONSTRAINT authz_actions_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.authz_applications(id);


--
-- Name: authz_audit_events authz_audit_events_action_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_audit_events
    ADD CONSTRAINT authz_audit_events_action_id_fkey FOREIGN KEY (action_id) REFERENCES public.authz_actions(action_id);


--
-- Name: authz_audit_events authz_audit_events_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_audit_events
    ADD CONSTRAINT authz_audit_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES auth.users(id);


--
-- Name: authz_audit_events authz_audit_events_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_audit_events
    ADD CONSTRAINT authz_audit_events_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.authz_applications(id);


--
-- Name: authz_audit_events authz_audit_events_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_audit_events
    ADD CONSTRAINT authz_audit_events_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.authz_credentials(id);


--
-- Name: authz_audit_events authz_audit_events_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_audit_events
    ADD CONSTRAINT authz_audit_events_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.authz_devices(id);


--
-- Name: authz_audit_events authz_audit_events_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_audit_events
    ADD CONSTRAINT authz_audit_events_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.authz_requests(id);


--
-- Name: authz_credentials authz_credentials_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_credentials
    ADD CONSTRAINT authz_credentials_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.authz_applications(id);


--
-- Name: authz_credentials authz_credentials_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_credentials
    ADD CONSTRAINT authz_credentials_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.authz_devices(id);


--
-- Name: authz_credentials authz_credentials_issued_to_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_credentials
    ADD CONSTRAINT authz_credentials_issued_to_user_id_fkey FOREIGN KEY (issued_to_user_id) REFERENCES auth.users(id);


--
-- Name: authz_credentials authz_credentials_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_credentials
    ADD CONSTRAINT authz_credentials_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.authz_requests(id);


--
-- Name: authz_decisions authz_decisions_action_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_decisions
    ADD CONSTRAINT authz_decisions_action_id_fkey FOREIGN KEY (action_id) REFERENCES public.authz_actions(action_id);


--
-- Name: authz_decisions authz_decisions_decided_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_decisions
    ADD CONSTRAINT authz_decisions_decided_by_user_id_fkey FOREIGN KEY (decided_by_user_id) REFERENCES auth.users(id);


--
-- Name: authz_decisions authz_decisions_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_decisions
    ADD CONSTRAINT authz_decisions_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.authz_devices(id);


--
-- Name: authz_decisions authz_decisions_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_decisions
    ADD CONSTRAINT authz_decisions_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.authz_requests(id) ON DELETE CASCADE;


--
-- Name: authz_devices authz_devices_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_devices
    ADD CONSTRAINT authz_devices_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.authz_applications(id);


--
-- Name: authz_devices authz_devices_authorized_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_devices
    ADD CONSTRAINT authz_devices_authorized_by_user_id_fkey FOREIGN KEY (authorized_by_user_id) REFERENCES auth.users(id);


--
-- Name: authz_requests authz_requests_action_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_requests
    ADD CONSTRAINT authz_requests_action_id_fkey FOREIGN KEY (action_id) REFERENCES public.authz_actions(action_id);


--
-- Name: authz_requests authz_requests_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_requests
    ADD CONSTRAINT authz_requests_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.authz_applications(id);


--
-- Name: authz_requests authz_requests_approved_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_requests
    ADD CONSTRAINT authz_requests_approved_by_user_id_fkey FOREIGN KEY (approved_by_user_id) REFERENCES auth.users(id);


--
-- Name: authz_requests authz_requests_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_requests
    ADD CONSTRAINT authz_requests_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.authz_devices(id);


--
-- Name: authz_requests authz_requests_requesting_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_requests
    ADD CONSTRAINT authz_requests_requesting_user_id_fkey FOREIGN KEY (requesting_user_id) REFERENCES auth.users(id);


--
-- Name: authz_revocations authz_revocations_credential_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_revocations
    ADD CONSTRAINT authz_revocations_credential_id_fkey FOREIGN KEY (credential_id) REFERENCES public.authz_credentials(id) ON DELETE CASCADE;


--
-- Name: authz_revocations authz_revocations_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_revocations
    ADD CONSTRAINT authz_revocations_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.authz_devices(id) ON DELETE CASCADE;


--
-- Name: authz_revocations authz_revocations_revoked_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.authz_revocations
    ADD CONSTRAINT authz_revocations_revoked_by_user_id_fkey FOREIGN KEY (revoked_by_user_id) REFERENCES auth.users(id);


--
-- Name: banned_users banned_users_banned_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.banned_users
    ADD CONSTRAINT banned_users_banned_by_fkey FOREIGN KEY (banned_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: banned_users banned_users_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.banned_users
    ADD CONSTRAINT banned_users_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: case_dossiers case_dossiers_alert_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.case_dossiers
    ADD CONSTRAINT case_dossiers_alert_id_fkey FOREIGN KEY (alert_id) REFERENCES public.alerts(id) ON DELETE SET NULL;


--
-- Name: case_dossiers case_dossiers_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.case_dossiers
    ADD CONSTRAINT case_dossiers_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id);


--
-- Name: case_dossiers case_dossiers_workstation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.case_dossiers
    ADD CONSTRAINT case_dossiers_workstation_id_fkey FOREIGN KEY (workstation_id) REFERENCES public.workstations(id) ON DELETE CASCADE;


--
-- Name: device_audit_logs device_audit_logs_linked_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_audit_logs
    ADD CONSTRAINT device_audit_logs_linked_device_id_fkey FOREIGN KEY (linked_device_id) REFERENCES public.linked_devices(id) ON DELETE SET NULL;


--
-- Name: device_audit_logs device_audit_logs_pairing_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_audit_logs
    ADD CONSTRAINT device_audit_logs_pairing_session_id_fkey FOREIGN KEY (pairing_session_id) REFERENCES public.pairing_sessions(id) ON DELETE SET NULL;


--
-- Name: device_audit_logs device_audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_audit_logs
    ADD CONSTRAINT device_audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: device_tokens device_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_tokens
    ADD CONSTRAINT device_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: evidence_logs evidence_logs_alert_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evidence_logs
    ADD CONSTRAINT evidence_logs_alert_id_fkey FOREIGN KEY (alert_id) REFERENCES public.alerts(id) ON DELETE CASCADE;


--
-- Name: license_events license_events_license_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.license_events
    ADD CONSTRAINT license_events_license_id_fkey FOREIGN KEY (license_id) REFERENCES public.licenses(id) ON DELETE CASCADE;


--
-- Name: license_events license_events_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.license_events
    ADD CONSTRAINT license_events_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.license_nodes(id) ON DELETE CASCADE;


--
-- Name: license_nodes license_nodes_auth_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.license_nodes
    ADD CONSTRAINT license_nodes_auth_user_id_fkey FOREIGN KEY (auth_user_id) REFERENCES auth.users(id);


--
-- Name: license_nodes license_nodes_license_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.license_nodes
    ADD CONSTRAINT license_nodes_license_id_fkey FOREIGN KEY (license_id) REFERENCES public.licenses(id) ON DELETE CASCADE;


--
-- Name: linked_devices linked_devices_pairing_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.linked_devices
    ADD CONSTRAINT linked_devices_pairing_session_id_fkey FOREIGN KEY (pairing_session_id) REFERENCES public.pairing_sessions(id) ON DELETE SET NULL;


--
-- Name: linked_devices linked_devices_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.linked_devices
    ADD CONSTRAINT linked_devices_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: pairing_sessions pairing_sessions_initiator_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pairing_sessions
    ADD CONSTRAINT pairing_sessions_initiator_id_fkey FOREIGN KEY (initiator_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: phone_otp_sessions phone_otp_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.phone_otp_sessions
    ADD CONSTRAINT phone_otp_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: profiles profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: security_audit_logs security_audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.security_audit_logs
    ADD CONSTRAINT security_audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: unauthorized_events unauthorized_events_workstation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unauthorized_events
    ADD CONSTRAINT unauthorized_events_workstation_id_fkey FOREIGN KEY (workstation_id) REFERENCES public.workstations(id) ON DELETE CASCADE;


--
-- Name: unban_requests unban_requests_resolved_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unban_requests
    ADD CONSTRAINT unban_requests_resolved_by_fkey FOREIGN KEY (resolved_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: unban_requests unban_requests_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unban_requests
    ADD CONSTRAINT unban_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_preferences user_preferences_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_sessions user_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_totp user_totp_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_totp
    ADD CONSTRAINT user_totp_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: workstations workstations_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.workstations
    ADD CONSTRAINT workstations_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: app_categories Admins can manage app_categories; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins can manage app_categories" ON public.app_categories USING (true) WITH CHECK (true);


--
-- Name: case_dossiers Admins can manage dossiers; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins can manage dossiers" ON public.case_dossiers USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'principal'::public.app_role, 'teacher'::public.app_role]));


--
-- Name: agent_configs Admins manage agent configs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins manage agent configs" ON public.agent_configs USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: alerts Admins manage alerts; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins manage alerts" ON public.alerts USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: allowed_apps Admins manage apps; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins manage apps" ON public.allowed_apps USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: evidence_logs Admins manage evidence; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins manage evidence" ON public.evidence_logs USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: system_settings Admins manage settings; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins manage settings" ON public.system_settings USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: workstations Admins manage workstations; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins manage workstations" ON public.workstations USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: agent_health Admins view agent health; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins view agent health" ON public.agent_health FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: alerts Admins view alerts; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins view alerts" ON public.alerts FOR SELECT USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: profiles Admins view all profiles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins view all profiles" ON public.profiles FOR SELECT USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: user_roles Admins view all roles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins view all roles" ON public.user_roles FOR SELECT USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: allowed_apps Admins view apps; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins view apps" ON public.allowed_apps FOR SELECT USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: evidence_logs Admins view evidence; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins view evidence" ON public.evidence_logs FOR SELECT USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: system_settings Admins view settings; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins view settings" ON public.system_settings FOR SELECT USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: workstations Admins view workstations; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Admins view workstations" ON public.workstations FOR SELECT USING (public.has_role(auth.uid(), 'admin'::public.app_role));


--
-- Name: activity_logs Agent anon insert activity; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent anon insert activity" ON public.activity_logs FOR INSERT TO anon WITH CHECK (true);


--
-- Name: activity_logs Agent anon insert activity_logs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent anon insert activity_logs" ON public.activity_logs FOR INSERT TO anon WITH CHECK (true);


--
-- Name: agent_health Agent anon insert agent_health; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent anon insert agent_health" ON public.agent_health FOR INSERT TO anon WITH CHECK (true);


--
-- Name: alerts Agent anon insert alerts; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent anon insert alerts" ON public.alerts FOR INSERT TO anon WITH CHECK (true);


--
-- Name: device_tokens Agent anon insert device_tokens; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent anon insert device_tokens" ON public.device_tokens FOR INSERT TO anon WITH CHECK (true);


--
-- Name: evidence_logs Agent insert evidence_logs; Type: POLICY; Schema: public; Owner: postgres
-- SECURITY FIX (2026-09): was two duplicate `TO anon WITH CHECK (true)`
-- policies ("Agent anon insert evidence" / "Agent anon insert
-- evidence_logs") letting anyone with the public anon key fabricate
-- disciplinary evidence for any workstation. The real agent always
-- authenticates via SessionManager.get_client() (client.auth.set_session)
-- before writing this table, so `authenticated` is a drop-in replacement.
--

CREATE POLICY "Agent insert evidence_logs" ON public.evidence_logs FOR INSERT TO authenticated WITH CHECK (true);


--
-- Name: workstations Agent insert workstations; Type: POLICY; Schema: public; Owner: postgres
-- SECURITY FIX (2026-09): was `TO anon WITH CHECK (true)` — anyone with
-- the public anon key could create arbitrary workstation rows. The agent
-- always inserts via an authenticated SessionManager client.
--

CREATE POLICY "Agent insert workstations" ON public.workstations FOR INSERT TO authenticated WITH CHECK (true);


--
-- Name: admin_actions Agent select admin_actions; Type: POLICY; Schema: public; Owner: postgres
-- SECURITY FIX (2026-09): was `TO anon USING (true)` — anyone with the
-- public anon key could read every workstation's command queue. See
-- report.md finding #1.
--

CREATE POLICY "Agent select admin_actions" ON public.admin_actions FOR SELECT TO authenticated USING (true);


--
-- Name: agent_configs Agent anon select agent_configs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent anon select agent_configs" ON public.agent_configs FOR SELECT TO anon USING (true);


--
-- Name: allowed_apps Agent anon select allowed_apps; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent anon select allowed_apps" ON public.allowed_apps FOR SELECT TO anon USING (true);


--
-- Name: system_settings Agent select settings; Type: POLICY; Schema: public; Owner: postgres
-- SECURITY FIX (2026-09): was `TO anon USING (true)`.
--

CREATE POLICY "Agent select settings" ON public.system_settings FOR SELECT TO authenticated USING (true);


--
-- Name: admin_actions Agent update admin_actions; Type: POLICY; Schema: public; Owner: postgres
-- SECURITY FIX (2026-09): removed duplicate "Agent anon select
-- workstations" policy here (a `TO authenticated, anon` version of the
-- same select already exists below and has been tightened there); and
-- tightened this update policy from `TO anon` to `TO authenticated` —
-- unrestricted anon UPDATE let anyone flip a real freeze/shutdown
-- command's status to suppress it before the agent processed it.
--

CREATE POLICY "Agent update admin_actions" ON public.admin_actions FOR UPDATE TO authenticated USING (true) WITH CHECK (true);


--
-- Name: device_tokens Agent anon update device_tokens; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent anon update device_tokens" ON public.device_tokens FOR UPDATE TO anon USING (true) WITH CHECK (true);


--
-- Name: evidence_logs Agent update evidence_logs; Type: POLICY; Schema: public; Owner: postgres
-- SECURITY FIX (2026-09): was two duplicate `TO anon` policies letting
-- anyone with the public anon key overwrite existing evidence
-- (screenshot_url/webcam_url) for any workstation.
--

CREATE POLICY "Agent update evidence_logs" ON public.evidence_logs FOR UPDATE TO authenticated USING (true) WITH CHECK (true);


-- SECURITY FIX (2026-09): removed "Agent anon update system_settings"
-- (`TO anon USING (true)`) with no replacement — Obylon.py never writes
-- this table (only `.select("focus_mode")`), so only "Admins manage
-- settings" (has_role(auth.uid(),'admin')) should be able to write it.

--
-- Name: workstations Agent update workstations; Type: POLICY; Schema: public; Owner: postgres
-- SECURITY FIX (2026-09): was `TO anon`.
--

CREATE POLICY "Agent update workstations" ON public.workstations FOR UPDATE TO authenticated USING (true) WITH CHECK (true);


-- SECURITY FIX (2026-09): removed "Agent delete unauthorized events"
-- (`TO authenticated, anon USING (true)`) entirely — Obylon.py never
-- calls .table("unauthorized_events").delete(...) anywhere, so this let
-- anyone with just the anon key wipe violation history for every
-- workstation with no legitimate use of the capability at all.

--
-- Name: unauthorized_events Agent insert unauthorized events; Type: POLICY; Schema: public; Owner: postgres
-- SECURITY FIX (2026-09): dropped `anon` from the role list.
--

CREATE POLICY "Agent insert unauthorized events" ON public.unauthorized_events FOR INSERT TO authenticated, service_role WITH CHECK (true);


--
-- Name: agent_configs Agent read config; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Agent read config" ON public.agent_configs FOR SELECT TO authenticated, anon USING (true);


--
-- Name: unauthorized_events Agent select unauthorized events; Type: POLICY; Schema: public; Owner: postgres
--

-- SECURITY FIX (2026-09): dropped `anon` from the role list.
CREATE POLICY "Agent select unauthorized events" ON public.unauthorized_events FOR SELECT TO authenticated USING (true);


--
-- Name: workstations Agent select workstations; Type: POLICY; Schema: public; Owner: postgres
--

-- SECURITY FIX (2026-09): dropped `anon` from the role list.
CREATE POLICY "Agent select workstations" ON public.workstations FOR SELECT TO authenticated USING (true);


-- SECURITY FIX (2026-09): removed "Allow anon insert" on
-- unauthorized_events — a redundant `TO anon` duplicate of the insert
-- policy above, already fixed there.


--
-- Name: alerts Allow anon inserts on alerts; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Allow anon inserts on alerts" ON public.alerts FOR INSERT TO anon WITH CHECK (true);


--
-- Name: unban_requests Banned users can insert unban requests; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Banned users can insert unban requests" ON public.unban_requests FOR INSERT TO authenticated WITH CHECK ((user_id = auth.uid()));


--
-- Name: user_roles Bootstrap first privileged user; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Bootstrap first privileged user" ON public.user_roles FOR INSERT TO authenticated WITH CHECK (((auth.uid() = user_id) AND (role = ANY (ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role])) AND (NOT (EXISTS ( SELECT 1
   FROM public.user_roles user_roles_1
  WHERE (user_roles_1.role = ANY (ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role])))))));


--
-- Name: user_roles Dev manages all roles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Dev manages all roles" ON public.user_roles TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role])) WITH CHECK (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role]));


--
-- Name: banned_users Dev/Admin/Principal can view all banned users; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Dev/Admin/Principal can view all banned users" ON public.banned_users FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: licenses Developer Manage Licenses; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Developer Manage Licenses" ON public.licenses TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role])) WITH CHECK (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role]));


--
-- Name: license_nodes Developer Manage Nodes; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Developer Manage Nodes" ON public.license_nodes TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role])) WITH CHECK (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role]));


--
-- Name: security_audit_logs Elevated audit select; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated audit select" ON public.security_audit_logs FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: banned_users Elevated ban users; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated ban users" ON public.banned_users FOR INSERT TO authenticated WITH CHECK (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: admin_actions Elevated delete actions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated delete actions" ON public.admin_actions FOR DELETE TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: profiles Elevated delete profiles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated delete profiles" ON public.profiles FOR DELETE TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: admin_actions Elevated insert actions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated insert actions" ON public.admin_actions FOR INSERT TO authenticated WITH CHECK (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: agent_configs Elevated manage agent configs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated manage agent configs" ON public.agent_configs TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'principal'::public.app_role, 'admin'::public.app_role, 'teacher'::public.app_role])) WITH CHECK (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'principal'::public.app_role, 'admin'::public.app_role, 'teacher'::public.app_role]));


--
-- Name: unauthorized_window_settings Elevated manage window settings; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated manage window settings" ON public.unauthorized_window_settings TO authenticated, anon USING (true) WITH CHECK (true);


--
-- Name: agent_configs Elevated read agent configs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated read agent configs" ON public.agent_configs FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'principal'::public.app_role, 'admin'::public.app_role, 'teacher'::public.app_role]));


--
-- Name: user_roles Elevated read all roles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated read all roles" ON public.user_roles FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role, 'teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: unauthorized_window_settings Elevated read window settings; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated read window settings" ON public.unauthorized_window_settings FOR SELECT TO authenticated, anon USING (true);


--
-- Name: banned_users Elevated roles can ban users; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated roles can ban users" ON public.banned_users FOR INSERT TO authenticated WITH CHECK (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: banned_users Elevated roles can unban users; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated roles can unban users" ON public.banned_users FOR DELETE TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: unban_requests Elevated roles can update unban requests; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated roles can update unban requests" ON public.unban_requests FOR UPDATE TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: unban_requests Elevated roles can view unban requests; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated roles can view unban requests" ON public.unban_requests FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: admin_actions Elevated select actions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select actions" ON public.admin_actions FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role, 'teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: activity_logs Elevated select activity_logs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select activity_logs" ON public.activity_logs FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: agent_configs Elevated select agent_configs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select agent_configs" ON public.agent_configs FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: agent_health Elevated select agent_health; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select agent_health" ON public.agent_health FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: alerts Elevated select alerts; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select alerts" ON public.alerts FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: allowed_apps Elevated select allowed_apps; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select allowed_apps" ON public.allowed_apps FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: case_dossiers Elevated select case_dossiers; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select case_dossiers" ON public.case_dossiers FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: device_tokens Elevated select device_tokens; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select device_tokens" ON public.device_tokens FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: evidence_logs Elevated select evidence_logs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select evidence_logs" ON public.evidence_logs FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: system_settings Elevated select system_settings; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select system_settings" ON public.system_settings FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: workstations Elevated select workstations; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated select workstations" ON public.workstations FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), '{dev,admin,principal,teacher,helper}'::public.app_role[]));


--
-- Name: banned_users Elevated unban users; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated unban users" ON public.banned_users FOR DELETE TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: admin_actions Elevated update actions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated update actions" ON public.admin_actions FOR UPDATE TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role])) WITH CHECK (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: unban_requests Elevated update unban; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated update unban" ON public.unban_requests FOR UPDATE TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: profiles Elevated view all profiles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated view all profiles" ON public.profiles FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: banned_users Elevated view banned; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated view banned" ON public.banned_users FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: unban_requests Elevated view unban; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Elevated view unban" ON public.unban_requests FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['dev'::public.app_role, 'admin'::public.app_role, 'principal'::public.app_role]));


--
-- Name: app_categories Enable manage access for app_categories; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Enable manage access for app_categories" ON public.app_categories TO authenticated, anon USING (true) WITH CHECK (true);


--
-- Name: app_categories Enable read access for app_categories; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Enable read access for app_categories" ON public.app_categories FOR SELECT TO authenticated, anon USING (true);


--
-- Name: licenses Node Self Read License; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Node Self Read License" ON public.licenses FOR SELECT TO authenticated USING ((id IN ( SELECT license_nodes.license_id
   FROM public.license_nodes
  WHERE (license_nodes.auth_user_id = auth.uid()))));


--
-- Name: security_audit_logs Own audit insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own audit insert" ON public.security_audit_logs FOR INSERT TO authenticated WITH CHECK ((auth.uid() = user_id));


--
-- Name: security_audit_logs Own audit select; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own audit select" ON public.security_audit_logs FOR SELECT TO authenticated USING ((auth.uid() = user_id));


--
-- Name: user_preferences Own prefs insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own prefs insert" ON public.user_preferences FOR INSERT TO authenticated WITH CHECK ((auth.uid() = user_id));


--
-- Name: user_preferences Own prefs select; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own prefs select" ON public.user_preferences FOR SELECT TO authenticated USING ((auth.uid() = user_id));


--
-- Name: user_preferences Own prefs update; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own prefs update" ON public.user_preferences FOR UPDATE TO authenticated USING ((auth.uid() = user_id));


--
-- Name: user_sessions Own sessions delete; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own sessions delete" ON public.user_sessions FOR DELETE TO authenticated USING ((auth.uid() = user_id));


--
-- Name: user_sessions Own sessions insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own sessions insert" ON public.user_sessions FOR INSERT TO authenticated WITH CHECK ((auth.uid() = user_id));


--
-- Name: user_sessions Own sessions select; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own sessions select" ON public.user_sessions FOR SELECT TO authenticated USING ((auth.uid() = user_id));


--
-- Name: user_sessions Own sessions update; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Own sessions update" ON public.user_sessions FOR UPDATE TO authenticated USING ((auth.uid() = user_id));


--
-- Name: user_roles Principal manages subordinate roles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Principal manages subordinate roles" ON public.user_roles TO authenticated USING ((public.has_any_role(auth.uid(), ARRAY['principal'::public.app_role, 'admin'::public.app_role]) AND (role = ANY (ARRAY['teacher'::public.app_role, 'helper'::public.app_role])))) WITH CHECK ((public.has_any_role(auth.uid(), ARRAY['principal'::public.app_role, 'admin'::public.app_role]) AND (role = ANY (ARRAY['teacher'::public.app_role, 'helper'::public.app_role]))));


--
-- Name: phone_otp_sessions Service full otp; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Service full otp" ON public.phone_otp_sessions TO service_role USING (true) WITH CHECK (true);


--
-- Name: phone_otp_sessions Service role full access; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Service role full access" ON public.phone_otp_sessions TO service_role USING (true) WITH CHECK (true);


--
-- Name: user_totp Service role full access; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Service role full access" ON public.user_totp TO service_role USING (true) WITH CHECK (true);


--
-- Name: admin_actions Staff view actions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Staff view actions" ON public.admin_actions FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: agent_configs Staff view agent configs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Staff view agent configs" ON public.agent_configs FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: alerts Staff view alerts; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Staff view alerts" ON public.alerts FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: allowed_apps Staff view apps; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Staff view apps" ON public.allowed_apps FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: evidence_logs Staff view evidence; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Staff view evidence" ON public.evidence_logs FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: profiles Staff view profiles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Staff view profiles" ON public.profiles FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: system_settings Staff view settings; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Staff view settings" ON public.system_settings FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: workstations Staff view workstations; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Staff view workstations" ON public.workstations FOR SELECT USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role, 'helper'::public.app_role]));


--
-- Name: user_roles Teacher manages helpers; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Teacher manages helpers" ON public.user_roles TO authenticated USING ((public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role]) AND (role = 'helper'::public.app_role))) WITH CHECK ((public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role]) AND (role = 'helper'::public.app_role)));


--
-- Name: profiles Teacher view profiles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Teacher view profiles" ON public.profiles FOR SELECT TO authenticated USING (public.has_any_role(auth.uid(), ARRAY['teacher'::public.app_role]));


--
-- Name: user_sessions Users can delete their own sessions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can delete their own sessions" ON public.user_sessions FOR DELETE USING ((auth.uid() = user_id));


--
-- Name: security_audit_logs Users can insert their own audit logs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can insert their own audit logs" ON public.security_audit_logs FOR INSERT WITH CHECK ((auth.uid() = user_id));


--
-- Name: user_preferences Users can insert their own preferences; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can insert their own preferences" ON public.user_preferences FOR INSERT WITH CHECK ((auth.uid() = user_id));


--
-- Name: user_sessions Users can insert their own sessions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can insert their own sessions" ON public.user_sessions FOR INSERT WITH CHECK ((auth.uid() = user_id));


--
-- Name: pairing_sessions Users can read own pairing sessions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read own pairing sessions" ON public.pairing_sessions FOR SELECT TO authenticated USING (((initiator_id = ( SELECT auth.uid() AS uid)) OR ((status = 'waiting'::text) AND (initiator_id IS NULL))));


--
-- Name: linked_devices Users can update own linked devices; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can update own linked devices" ON public.linked_devices FOR UPDATE TO authenticated USING ((( SELECT auth.uid() AS uid) = user_id)) WITH CHECK ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: user_preferences Users can update their own preferences; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can update their own preferences" ON public.user_preferences FOR UPDATE USING ((auth.uid() = user_id));


--
-- Name: user_sessions Users can update their own sessions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can update their own sessions" ON public.user_sessions FOR UPDATE USING ((auth.uid() = user_id));


--
-- Name: device_audit_logs Users can view own device audit logs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can view own device audit logs" ON public.device_audit_logs FOR SELECT TO authenticated USING ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: linked_devices Users can view own linked devices; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can view own linked devices" ON public.linked_devices FOR SELECT TO authenticated USING ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: user_totp Users can view own totp; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can view own totp" ON public.user_totp FOR SELECT TO authenticated USING ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: security_audit_logs Users can view their own audit logs; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can view their own audit logs" ON public.security_audit_logs FOR SELECT USING ((auth.uid() = user_id));


--
-- Name: banned_users Users can view their own ban status; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can view their own ban status" ON public.banned_users FOR SELECT TO authenticated USING ((user_id = auth.uid()));


--
-- Name: user_preferences Users can view their own preferences; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can view their own preferences" ON public.user_preferences FOR SELECT USING ((auth.uid() = user_id));


--
-- Name: user_sessions Users can view their own sessions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can view their own sessions" ON public.user_sessions FOR SELECT USING ((auth.uid() = user_id));


--
-- Name: unban_requests Users can view their own unban requests; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can view their own unban requests" ON public.unban_requests FOR SELECT TO authenticated USING ((user_id = auth.uid()));


--
-- Name: unban_requests Users create unban; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users create unban" ON public.unban_requests FOR INSERT TO authenticated WITH CHECK ((user_id = auth.uid()));


--
-- Name: profiles Users insert own profile; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users insert own profile" ON public.profiles FOR INSERT WITH CHECK ((auth.uid() = user_id));


--
-- Name: user_roles Users read own roles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users read own roles" ON public.user_roles FOR SELECT TO authenticated USING ((user_id = auth.uid()));


--
-- Name: profiles Users update own profile; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users update own profile" ON public.profiles FOR UPDATE USING ((auth.uid() = user_id));


--
-- Name: banned_users Users view own ban; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users view own ban" ON public.banned_users FOR SELECT TO authenticated USING ((user_id = auth.uid()));


--
-- Name: phone_otp_sessions Users view own otp; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users view own otp" ON public.phone_otp_sessions FOR SELECT TO authenticated USING ((auth.uid() = user_id));


--
-- Name: profiles Users view own profile; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users view own profile" ON public.profiles FOR SELECT USING ((auth.uid() = user_id));


--
-- Name: user_roles Users view own roles; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users view own roles" ON public.user_roles FOR SELECT USING ((auth.uid() = user_id));


--
-- Name: phone_otp_sessions Users view own sessions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users view own sessions" ON public.phone_otp_sessions FOR SELECT TO authenticated USING ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: unban_requests Users view own unban; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users view own unban" ON public.unban_requests FOR SELECT TO authenticated USING ((user_id = auth.uid()));


--
-- Name: activity_logs activity_logs insert service; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "activity_logs insert service" ON public.activity_logs FOR INSERT TO service_role WITH CHECK (true);


--
-- Name: activity_logs activity_logs read auth; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "activity_logs read auth" ON public.activity_logs FOR SELECT TO authenticated USING (true);


--
-- Name: agent_configs; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.agent_configs ENABLE ROW LEVEL SECURITY;

--
-- Name: app_categories; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.app_categories ENABLE ROW LEVEL SECURITY;

--
-- Name: authz_actions; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.authz_actions ENABLE ROW LEVEL SECURITY;

--
-- Name: authz_applications; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.authz_applications ENABLE ROW LEVEL SECURITY;

--
-- Name: authz_audit_events; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.authz_audit_events ENABLE ROW LEVEL SECURITY;

--
-- Name: authz_credentials; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.authz_credentials ENABLE ROW LEVEL SECURITY;

--
-- Name: authz_decisions; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.authz_decisions ENABLE ROW LEVEL SECURITY;

--
-- Name: authz_devices; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.authz_devices ENABLE ROW LEVEL SECURITY;

--
-- Name: authz_requests; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.authz_requests ENABLE ROW LEVEL SECURITY;

--
-- Name: authz_revocations; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.authz_revocations ENABLE ROW LEVEL SECURITY;

--
-- Name: device_audit_logs; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.device_audit_logs ENABLE ROW LEVEL SECURITY;

--
-- Name: device_tokens device_tokens_self_delete; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY device_tokens_self_delete ON public.device_tokens FOR DELETE TO authenticated USING ((auth.uid() = user_id));


--
-- Name: device_tokens device_tokens_self_insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY device_tokens_self_insert ON public.device_tokens FOR INSERT TO authenticated WITH CHECK ((auth.uid() = user_id));


--
-- Name: device_tokens device_tokens_self_select; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY device_tokens_self_select ON public.device_tokens FOR SELECT TO authenticated USING ((auth.uid() = user_id));


--
-- Name: device_tokens device_tokens_self_update; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY device_tokens_self_update ON public.device_tokens FOR UPDATE TO authenticated USING ((auth.uid() = user_id));


--
-- Name: fastlane_events; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.fastlane_events ENABLE ROW LEVEL SECURITY;

--
-- Name: fastlane_events fastlane_events_insert_anon; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY fastlane_events_insert_anon ON public.fastlane_events FOR INSERT TO anon WITH CHECK (true);


--
-- Name: fastlane_events fastlane_events_select_authenticated; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY fastlane_events_select_authenticated ON public.fastlane_events FOR SELECT TO authenticated USING (true);


--
-- Name: license_events; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.license_events ENABLE ROW LEVEL SECURITY;

--
-- Name: license_nodes; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.license_nodes ENABLE ROW LEVEL SECURITY;

--
-- Name: licenses; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.licenses ENABLE ROW LEVEL SECURITY;

--
-- Name: linked_devices; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.linked_devices ENABLE ROW LEVEL SECURITY;

--
-- Name: license_nodes nodes_self_managed; Type: POLICY; Schema: public; Owner: postgres
--
-- BUGFIX (2026-09): was `TO authenticated USING (...) WITH CHECK (...)`
-- with no FOR clause, i.e. FOR ALL — a node's own agent could UPDATE or
-- DELETE its own row directly (e.g. undo a reclaim). No legitimate code
-- path needs more than SELECT here: every real write to license_nodes
-- goes through activate_license_node(), a SECURITY DEFINER RPC that
-- bypasses RLS entirely. See db_license_node_reclaim_fix.sql.
--

CREATE POLICY nodes_self_managed ON public.license_nodes
  FOR SELECT TO authenticated USING ((auth.uid() = auth_user_id));


--
-- Name: pairing_sessions; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.pairing_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: security_audit_logs; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.security_audit_logs ENABLE ROW LEVEL SECURITY;

--
-- Name: unauthorized_events; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.unauthorized_events ENABLE ROW LEVEL SECURITY;

--
-- Name: user_totp; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.user_totp ENABLE ROW LEVEL SECURITY;

--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: postgres
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO anon;
GRANT ALL ON SCHEMA public TO authenticated;
GRANT ALL ON SCHEMA public TO service_role;


--
-- Name: FUNCTION claim_telegram_phone(p_user_id uuid, p_telegram_chat_id bigint, p_phone text, p_ip_address text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.claim_telegram_phone(p_user_id uuid, p_telegram_chat_id bigint, p_phone text, p_ip_address text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.claim_telegram_phone(p_user_id uuid, p_telegram_chat_id bigint, p_phone text, p_ip_address text) TO service_role;


--
-- Name: FUNCTION handle_new_user(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.handle_new_user() FROM PUBLIC;


--
-- Name: FUNCTION has_any_role(_user_id uuid, _roles public.app_role[]); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.has_any_role(_user_id uuid, _roles public.app_role[]) TO authenticated;
GRANT ALL ON FUNCTION public.has_any_role(_user_id uuid, _roles public.app_role[]) TO service_role;


--
-- Name: FUNCTION has_role(_user_id uuid, _role public.app_role); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.has_role(_user_id uuid, _role public.app_role) TO authenticated;
GRANT ALL ON FUNCTION public.has_role(_user_id uuid, _role public.app_role) TO service_role;


--
-- Name: TABLE licenses; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.licenses TO anon;
GRANT ALL ON TABLE public.licenses TO authenticated;
GRANT ALL ON TABLE public.licenses TO service_role;


--
-- Name: FUNCTION run_retention_prune(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.run_retention_prune() FROM PUBLIC;
GRANT ALL ON FUNCTION public.run_retention_prune() TO service_role;


--
-- Name: FUNCTION update_updated_at_column(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.update_updated_at_column() FROM PUBLIC;


--
-- Name: FUNCTION users_due_for_backup(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.users_due_for_backup() FROM PUBLIC;
GRANT ALL ON FUNCTION public.users_due_for_backup() TO service_role;


--
-- Name: TABLE activity_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.activity_logs TO authenticated;
GRANT ALL ON TABLE public.activity_logs TO service_role;
GRANT ALL ON TABLE public.activity_logs TO anon;


--
-- Name: TABLE admin_actions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.admin_actions TO authenticated;
GRANT ALL ON TABLE public.admin_actions TO service_role;
GRANT ALL ON TABLE public.admin_actions TO anon;


--
-- Name: TABLE agent_configs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.agent_configs TO authenticated;
GRANT ALL ON TABLE public.agent_configs TO service_role;
GRANT ALL ON TABLE public.agent_configs TO anon;


--
-- Name: TABLE agent_health; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.agent_health TO authenticated;
GRANT ALL ON TABLE public.agent_health TO service_role;
GRANT ALL ON TABLE public.agent_health TO anon;


--
-- Name: TABLE alerts; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.alerts TO authenticated;
GRANT ALL ON TABLE public.alerts TO service_role;
GRANT ALL ON TABLE public.alerts TO anon;


--
-- Name: TABLE allowed_apps; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.allowed_apps TO authenticated;
GRANT ALL ON TABLE public.allowed_apps TO service_role;
GRANT ALL ON TABLE public.allowed_apps TO anon;


--
-- Name: TABLE app_categories; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.app_categories TO anon;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.app_categories TO authenticated;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.app_categories TO service_role;


--
-- Name: TABLE authz_actions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.authz_actions TO service_role;
GRANT SELECT ON TABLE public.authz_actions TO authenticated;


--
-- Name: TABLE authz_applications; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.authz_applications TO service_role;
GRANT SELECT ON TABLE public.authz_applications TO authenticated;


--
-- Name: TABLE authz_audit_events; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.authz_audit_events TO service_role;
GRANT SELECT ON TABLE public.authz_audit_events TO authenticated;


--
-- Name: TABLE authz_credentials; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.authz_credentials TO service_role;
GRANT SELECT ON TABLE public.authz_credentials TO authenticated;


--
-- Name: TABLE authz_decisions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.authz_decisions TO service_role;


--
-- Name: TABLE authz_devices; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.authz_devices TO service_role;
GRANT SELECT ON TABLE public.authz_devices TO authenticated;


--
-- Name: TABLE authz_requests; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.authz_requests TO service_role;
GRANT SELECT ON TABLE public.authz_requests TO authenticated;


--
-- Name: TABLE authz_revocations; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.authz_revocations TO service_role;


--
-- Name: TABLE banned_users; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.banned_users TO authenticated;
GRANT ALL ON TABLE public.banned_users TO service_role;
GRANT ALL ON TABLE public.banned_users TO anon;


--
-- Name: TABLE case_dossiers; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.case_dossiers TO authenticated;
GRANT ALL ON TABLE public.case_dossiers TO service_role;
GRANT ALL ON TABLE public.case_dossiers TO anon;


--
-- Name: TABLE device_audit_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.device_audit_logs TO authenticated;
GRANT ALL ON TABLE public.device_audit_logs TO service_role;


--
-- Name: TABLE device_tokens; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.device_tokens TO authenticated;
GRANT ALL ON TABLE public.device_tokens TO service_role;
GRANT ALL ON TABLE public.device_tokens TO anon;


--
-- Name: TABLE evidence_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.evidence_logs TO authenticated;
GRANT ALL ON TABLE public.evidence_logs TO service_role;
GRANT ALL ON TABLE public.evidence_logs TO anon;


--
-- Name: TABLE license_events; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.license_events TO anon;
GRANT ALL ON TABLE public.license_events TO authenticated;
GRANT ALL ON TABLE public.license_events TO service_role;


--
-- Name: TABLE license_nodes; Type: ACL; Schema: public; Owner: postgres
--

-- BUGFIX (2026-09): was `GRANT ALL ... TO anon` and `GRANT ALL ... TO
-- authenticated` — anon had no matching RLS policy so was already a
-- no-op in practice, but a dormant hazard (one future anon-scoped policy
-- or a temporarily-disabled RLS away from being exploitable); authenticated
-- had ALL, which combined with the old FOR-ALL nodes_self_managed policy
-- let a node write/delete its own row. Neither is needed: the only
-- legitimate write path is activate_license_node() (SECURITY DEFINER,
-- bypasses RLS). See db_license_node_reclaim_fix.sql.
GRANT SELECT ON TABLE public.license_nodes TO authenticated;
GRANT ALL ON TABLE public.license_nodes TO service_role;


--
-- Name: TABLE linked_devices; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,UPDATE ON TABLE public.linked_devices TO authenticated;
GRANT ALL ON TABLE public.linked_devices TO service_role;


--
-- Name: TABLE pairing_sessions; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.pairing_sessions TO authenticated;
GRANT ALL ON TABLE public.pairing_sessions TO service_role;


--
-- Name: TABLE phone_otp_sessions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.phone_otp_sessions TO authenticated;
GRANT ALL ON TABLE public.phone_otp_sessions TO service_role;
GRANT ALL ON TABLE public.phone_otp_sessions TO anon;


--
-- Name: TABLE profiles; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.profiles TO authenticated;
GRANT ALL ON TABLE public.profiles TO service_role;
GRANT ALL ON TABLE public.profiles TO anon;


--
-- Name: TABLE security_audit_logs; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.security_audit_logs TO authenticated;
GRANT ALL ON TABLE public.security_audit_logs TO service_role;
GRANT ALL ON TABLE public.security_audit_logs TO anon;


--
-- Name: TABLE system_settings; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.system_settings TO authenticated;
GRANT ALL ON TABLE public.system_settings TO anon;
GRANT ALL ON TABLE public.system_settings TO service_role;


--
-- Name: TABLE unauthorized_events; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.unauthorized_events TO anon;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.unauthorized_events TO service_role;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.unauthorized_events TO authenticated;


--
-- Name: TABLE unauthorized_window_settings; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.unauthorized_window_settings TO authenticated;
GRANT ALL ON TABLE public.unauthorized_window_settings TO service_role;
GRANT ALL ON TABLE public.unauthorized_window_settings TO anon;


--
-- Name: TABLE unban_requests; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.unban_requests TO authenticated;
GRANT ALL ON TABLE public.unban_requests TO service_role;
GRANT ALL ON TABLE public.unban_requests TO anon;


--
-- Name: TABLE user_preferences; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.user_preferences TO authenticated;
GRANT ALL ON TABLE public.user_preferences TO service_role;
GRANT ALL ON TABLE public.user_preferences TO anon;


--
-- Name: TABLE user_roles; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.user_roles TO authenticated;
GRANT ALL ON TABLE public.user_roles TO service_role;
GRANT ALL ON TABLE public.user_roles TO anon;


--
-- Name: TABLE user_sessions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.user_sessions TO authenticated;
GRANT ALL ON TABLE public.user_sessions TO service_role;
GRANT ALL ON TABLE public.user_sessions TO anon;


--
-- Name: TABLE user_totp; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.user_totp TO service_role;
GRANT SELECT ON TABLE public.user_totp TO authenticated;


--
-- Name: TABLE workstations; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.workstations TO authenticated;
GRANT ALL ON TABLE public.workstations TO service_role;
GRANT ALL ON TABLE public.workstations TO anon;


--
-- PostgreSQL database dump complete
--

\unrestrict eV2GTMfzT0Fq7erXgvK2UBfM1k9KSQp4AgBzhKD4Z8bf4HtEYfJVlo84Rtp2XAy



-- ==========================================
-- OBYLON AUTOMATION: PG_CRON JOBS
-- ==========================================
CREATE EXTENSION IF NOT EXISTS pg_cron;
SELECT cron.schedule('auto-backup-trigger', '0 0 * * *', '
    SELECT net.http_post(
      url := ''https://ozruikfnrmmvhvozgnoo.supabase.co/functions/v1/backup-service'',
      headers := ''{"Content-Type": "application/json"}''::jsonb,
      body := ''{"action": "auto"}''::jsonb
    );
  ');
SELECT cron.schedule('obylon-retention-prune', '15 3 * * *', ' SELECT public.run_retention_prune(); ');
SELECT cron.schedule('retention-alerts-evidence-prune', '0 3 * * *', '
    select
      public.prune_evidence_objects(30);
    select
      public.prune_alert_related_data(30);
  ');
SELECT cron.schedule('cron-prune-evidence-storage', '5 3 * * *', '
    select net.http_post(
      ''https://ozruikfnrmmvhvozgnoo.supabase.co/functions/v1/prune-evidence-objects'',
      ''application/json'',
      jsonb_build_object(''retentionDays'', 30, ''bucket'', ''evidence'')::text,
      ''{}''::jsonb
    );
  ');
SELECT cron.schedule('dormancy_reclaim_job', '0 0 * * *', '
    WITH reclaimed AS (
      UPDATE public.license_nodes
      SET status = ''reclaimed''
      WHERE last_seen_at < now() - interval ''120 days'' AND status = ''active''
      RETURNING id, license_id
    )
    INSERT INTO public.license_events (license_id, node_id, event_type, detail)
    SELECT license_id, id, ''reclaim'', ''{"reason": "dormancy"}''::jsonb
    FROM reclaimed;
    ');

-- ==========================================
-- OBYLON: REALTIME PUBLICATION MEMBERSHIP
-- ==========================================
-- BUGFIX (2026-09): license_nodes was never added to supabase_realtime,
-- so a client subscribing to postgres_changes on it (see
-- realtime_c2_listener in Obylon.py) would connect and subscribe
-- successfully but never actually receive an event — this table's
-- changes (including the new reclaim trigger above) were not being
-- broadcast at all. Guarded because ALTER PUBLICATION errors if the
-- table is already a member.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime'
      AND schemaname = 'public'
      AND tablename = 'license_nodes'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.license_nodes;
  END IF;
END $$;

