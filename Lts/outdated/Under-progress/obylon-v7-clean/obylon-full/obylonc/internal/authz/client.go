// Package authz is the untrusted Obylon-side half of Umbraxis
// authorization. It only asks the server for decisions; it never derives a
// role, grants a scope, or treats local vault state as authority.
package authz

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Client struct {
	BaseURL string
	HTTP    *http.Client
}

func NewClient(baseURL string) (*Client, error) {
	baseURL = strings.TrimRight(strings.TrimSpace(baseURL), "/")
	parsed, err := url.Parse(baseURL)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" {
		return nil, fmt.Errorf("Umbraxis server must be an HTTPS URL")
	}
	return &Client{BaseURL: baseURL, HTTP: &http.Client{Timeout: 15 * time.Second}}, nil
}

type CreateRequest struct {
	Application       string                 `json:"application"`
	DeviceName        string                 `json:"deviceName"`
	DevicePlatform    string                 `json:"devicePlatform"`
	DeviceFingerprint string                 `json:"deviceFingerprint"`
	RequestedScopes   []string               `json:"requestedScopes"`
	ActionID          string                 `json:"actionId"`
	Target            map[string]interface{} `json:"target"`
}

type DeviceAuthorization struct {
	RequestID               string `json:"request_id"`
	UserCode                string `json:"user_code"`
	VerificationURIComplete string `json:"verification_uri_complete"`
	DeviceCode              string `json:"device_code"`
	ExpiresIn               int    `json:"expires_in"`
	Interval                int    `json:"interval"`
}

type RequestStatus struct {
	Status        string   `json:"status"`
	ExpiresAt     string   `json:"expires_at"`
	GrantedScopes []string `json:"granted_scopes"`
}

type Credential struct {
	AccessToken  string   `json:"access_token"`
	RefreshToken string   `json:"refresh_token"`
	ExpiresAt    string   `json:"expires_at"`
	Scopes       []string `json:"scopes"`
	ActionID     string   `json:"action_id"`
	CredentialID string   `json:"credential_id"`
	DeviceID     string   `json:"device_id"`
}

type Decision struct {
	Decision  string   `json:"decision"`
	ActionID  string   `json:"action_id"`
	ExpiresAt string   `json:"expires_at"`
	Scopes    []string `json:"scopes"`
}

func (c *Client) Create(req CreateRequest) (DeviceAuthorization, error) {
	var out DeviceAuthorization
	return out, c.doJSON(http.MethodPost, "/api/auth/authorization-requests", "", req, &out)
}

func (c *Client) Poll(requestID, deviceCode string) (RequestStatus, error) {
	var out RequestStatus
	path := "/api/auth/authorization-requests/" + url.PathEscape(requestID) + "?device_code=" + url.QueryEscape(deviceCode)
	return out, c.doJSON(http.MethodGet, path, "", nil, &out)
}

func (c *Client) Exchange(requestID, deviceCode string) (Credential, error) {
	var out Credential
	path := "/api/auth/authorization-requests/" + url.PathEscape(requestID) + "/exchange"
	return out, c.doJSON(http.MethodPost, path, "", map[string]string{"device_code": deviceCode}, &out)
}

func (c *Client) Refresh(refreshToken string) (Credential, error) {
	var out Credential
	return out, c.doJSON(http.MethodPost, "/api/auth/credentials/refresh", "", map[string]string{"refresh_token": refreshToken}, &out)
}

func (c *Client) Authorize(accessToken, actionID string, target map[string]interface{}) (Decision, error) {
	var out Decision
	return out, c.doJSON(http.MethodPost, "/api/auth/authorize", accessToken, map[string]interface{}{"action_id": actionID, "target": target}, &out)
}

func (c *Client) Revoke(accessToken string) error {
	return c.doJSON(http.MethodPost, "/api/auth/credentials/revoke", accessToken, map[string]any{}, nil)
}

type APIError struct {
	Status int
	Code   string
}

func (e *APIError) Error() string {
	if e.Code != "" {
		return e.Code
	}
	return fmt.Sprintf("Umbraxis returned HTTP %d", e.Status)
}

func (c *Client) doJSON(method, path, bearer string, input, output interface{}) error {
	var body io.Reader
	if input != nil {
		encoded, err := json.Marshal(input)
		if err != nil {
			return err
		}
		body = bytes.NewReader(encoded)
	}
	req, err := http.NewRequest(method, c.BaseURL+path, body)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "Obylon-CLI/7.0.0")
	req.Header.Set("Sec-Fetch-Site", "same-origin")
	if input != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	response, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(response.Body, 128*1024))
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		var errorBody struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(raw, &errorBody)
		return &APIError{Status: response.StatusCode, Code: errorBody.Error}
	}
	if output != nil && len(raw) > 0 {
		if err := json.Unmarshal(raw, output); err != nil {
			return err
		}
	}
	return nil
}
