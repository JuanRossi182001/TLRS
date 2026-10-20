package main

import (
	"fmt"
	"os"
	"strings"
	timepkg "time"

	"github.com/BurntSushi/toml"
	"github.com/brocaar/lorawan"
)

type rawConfig struct {
	General struct {
		LogLevel string `toml:"log_level"`
	} `toml:"general"`

	ChirpStack struct {
		APIHost         string `toml:"api_host"`
		APIPort         int    `toml:"api_port"`
		APIToken        string `toml:"api_token"`
		TenantID        string `toml:"tenant_id"`
		ApplicationID   string `toml:"application_id"`
		DeviceProfileID string `toml:"device_profile_id"`
	} `toml:"chirpstack"`

	MQTT struct {
		Server   string `toml:"server"`
		Username string `toml:"username"`
		Password string `toml:"password"`
	} `toml:"mqtt"`

	Gateway struct {
		ID                   string `toml:"id"`
		EventTopicTemplate   string `toml:"event_topic_template"`
		CommandTopicTemplate string `toml:"command_topic_template"`
		DownlinkTxAckDelay   string `toml:"downlink_tx_ack_delay"`
	} `toml:"gateway"`

	Device struct {
		DevEUI          string `toml:"dev_eui"`
		JoinEUI         string `toml:"join_eui"`
		AppKey          string `toml:"app_key"`
		OTAADelay       string `toml:"otaa_delay"`
		UplinkInterval  string `toml:"uplink_interval"`
		ConfirmedUplink bool   `toml:"confirmed_uplink"`
		FPort           uint8  `toml:"f_port"`
		Frequency       int    `toml:"frequency"`
		Bandwidth       int    `toml:"bandwidth"`
		SpreadingFactor int    `toml:"spreading_factor"`
	} `toml:"device"`

	Scenario struct {
		Name           string  `toml:"name"`
		Duration       string  `toml:"duration"`
		ShapeHex       string  `toml:"shape_hex"`
		JitterMeters   float64 `toml:"jitter_meters"`
		AltitudeMeters float64 `toml:"altitude_meters"`
		AccuracyMeters float64 `toml:"accuracy_meters"`
		BatteryStart   int     `toml:"battery_start"`
	} `toml:"scenario"`
}

type Config struct {
	General struct {
		LogLevel string
	}
	ChirpStack struct {
		APIHost         string
		APIPort         int
		APIToken        string
		TenantID        string
		ApplicationID   string
		DeviceProfileID string
	}
	MQTT struct {
		Server   string
		Username string
		Password string
	}
	Gateway struct {
		ID                   lorawan.EUI64
		EventTopicTemplate   string
		CommandTopicTemplate string
		DownlinkTxAckDelay   timepkg.Duration
	}
	Device struct {
		DevEUI          lorawan.EUI64
		JoinEUI         lorawan.EUI64
		AppKey          lorawan.AES128Key
		OTAADelay       timepkg.Duration
		UplinkInterval  timepkg.Duration
		ConfirmedUplink bool
		FPort           uint8
		Frequency       int
		Bandwidth       int
		SpreadingFactor int
	}
	Scenario struct {
		Name           string
		Duration       timepkg.Duration
		ShapeHex       string
		JitterMeters   float64
		AltitudeMeters float64
		AccuracyMeters float64
		BatteryStart   int
	}
}

func LoadConfig(path string) (Config, error) {
	var raw rawConfig
	var cfg Config

	content, err := os.ReadFile(path)
	if err != nil {
		return cfg, err
	}

	if _, err := toml.Decode(os.ExpandEnv(string(content)), &raw); err != nil {
		return cfg, err
	}

	cfg.General.LogLevel = strings.ToLower(strings.TrimSpace(raw.General.LogLevel))
	cfg.ChirpStack.APIHost = raw.ChirpStack.APIHost
	cfg.ChirpStack.APIPort = raw.ChirpStack.APIPort
	cfg.ChirpStack.APIToken = raw.ChirpStack.APIToken
	cfg.ChirpStack.TenantID = raw.ChirpStack.TenantID
	cfg.ChirpStack.ApplicationID = raw.ChirpStack.ApplicationID
	cfg.ChirpStack.DeviceProfileID = raw.ChirpStack.DeviceProfileID
	cfg.MQTT.Server = raw.MQTT.Server
	cfg.MQTT.Username = raw.MQTT.Username
	cfg.MQTT.Password = raw.MQTT.Password
	cfg.Gateway.EventTopicTemplate = raw.Gateway.EventTopicTemplate
	cfg.Gateway.CommandTopicTemplate = raw.Gateway.CommandTopicTemplate
	cfg.Scenario.Name = strings.ToLower(strings.TrimSpace(raw.Scenario.Name))
	cfg.Scenario.ShapeHex = strings.TrimSpace(raw.Scenario.ShapeHex)
	cfg.Scenario.JitterMeters = raw.Scenario.JitterMeters
	cfg.Scenario.AltitudeMeters = raw.Scenario.AltitudeMeters
	cfg.Scenario.AccuracyMeters = raw.Scenario.AccuracyMeters
	cfg.Scenario.BatteryStart = raw.Scenario.BatteryStart
	cfg.Device.ConfirmedUplink = raw.Device.ConfirmedUplink
	cfg.Device.FPort = raw.Device.FPort
	cfg.Device.Frequency = raw.Device.Frequency
	cfg.Device.Bandwidth = raw.Device.Bandwidth
	cfg.Device.SpreadingFactor = raw.Device.SpreadingFactor

	if err := cfg.Gateway.ID.UnmarshalText([]byte(strings.TrimSpace(raw.Gateway.ID))); err != nil {
		return cfg, fmt.Errorf("parse gateway id: %w", err)
	}
	if err := cfg.Device.DevEUI.UnmarshalText([]byte(strings.TrimSpace(raw.Device.DevEUI))); err != nil {
		return cfg, fmt.Errorf("parse dev_eui: %w", err)
	}
	if err := cfg.Device.JoinEUI.UnmarshalText([]byte(strings.TrimSpace(raw.Device.JoinEUI))); err != nil {
		return cfg, fmt.Errorf("parse join_eui: %w", err)
	}
	if err := cfg.Device.AppKey.UnmarshalText([]byte(strings.TrimSpace(raw.Device.AppKey))); err != nil {
		return cfg, fmt.Errorf("parse app_key: %w", err)
	}

	if cfg.Gateway.DownlinkTxAckDelay, err = timepkg.ParseDuration(defaultString(raw.Gateway.DownlinkTxAckDelay, "2s")); err != nil {
		return cfg, fmt.Errorf("parse downlink_tx_ack_delay: %w", err)
	}
	if cfg.Device.OTAADelay, err = timepkg.ParseDuration(defaultString(raw.Device.OTAADelay, "0s")); err != nil {
		return cfg, fmt.Errorf("parse otaa_delay: %w", err)
	}
	if cfg.Device.UplinkInterval, err = timepkg.ParseDuration(defaultString(raw.Device.UplinkInterval, "15s")); err != nil {
		return cfg, fmt.Errorf("parse uplink_interval: %w", err)
	}
	if cfg.Scenario.Duration, err = timepkg.ParseDuration(defaultString(raw.Scenario.Duration, "0s")); err != nil {
		return cfg, fmt.Errorf("parse scenario duration: %w", err)
	}

	if cfg.MQTT.Server == "" {
		return cfg, fmt.Errorf("mqtt.server is required")
	}
	if cfg.Gateway.EventTopicTemplate == "" || cfg.Gateway.CommandTopicTemplate == "" {
		return cfg, fmt.Errorf("gateway topic templates are required")
	}
	if cfg.Scenario.Name == "" {
		cfg.Scenario.Name = "static"
	}
	if cfg.Scenario.AccuracyMeters <= 0 {
		cfg.Scenario.AccuracyMeters = 4.8
	}
	if cfg.Scenario.AltitudeMeters == 0 {
		cfg.Scenario.AltitudeMeters = 520.4
	}
	if cfg.Scenario.BatteryStart <= 0 {
		cfg.Scenario.BatteryStart = 87
	}
	if cfg.Device.FPort == 0 {
		cfg.Device.FPort = 10
	}

	return cfg, nil
}

func defaultString(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}
