package main

import (
	"bytes"
	"crypto/tls"
	"fmt"
	"log"
	"sync"
	"text/template"
	timepkg "time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
	"github.com/golang/protobuf/proto"

	"github.com/brocaar/lorawan"
	"github.com/chirpstack/chirpstack/api/go/v4/gw"
)

type Gateway struct {
	mqtt                 mqtt.Client
	gatewayID            lorawan.EUI64
	eventTopicTemplate   *template.Template
	commandTopicTemplate *template.Template
	downlinkTxAckDelay   timepkg.Duration
	devices              map[lorawan.EUI64]chan gw.DownlinkFrame
	deviceMu             sync.RWMutex
}

func NewGateway(cfg Config) (*Gateway, error) {
	eventTemplate, err := template.New("event").Parse(cfg.Gateway.EventTopicTemplate)
	if err != nil {
		return nil, fmt.Errorf("parse event topic template: %w", err)
	}
	commandTemplate, err := template.New("command").Parse(cfg.Gateway.CommandTopicTemplate)
	if err != nil {
		return nil, fmt.Errorf("parse command topic template: %w", err)
	}

	clientID := cfg.Gateway.ID.String()
	options := mqtt.NewClientOptions()
	options.AddBroker(cfg.MQTT.Server)
	options.SetClientID(clientID)
	options.SetUsername(cfg.MQTT.Username)
	options.SetPassword(cfg.MQTT.Password)
	options.SetCleanSession(true)
	options.SetAutoReconnect(true)
	options.SetOrderMatters(true)
	options.SetTLSConfig(&tls.Config{MinVersion: tls.VersionTLS12})

	client := mqtt.NewClient(options)
	if token := client.Connect(); token.Wait() && token.Error() != nil {
		return nil, fmt.Errorf("connect mqtt broker: %w", token.Error())
	}

	gateway := &Gateway{
		mqtt:                 client,
		gatewayID:            cfg.Gateway.ID,
		eventTopicTemplate:   eventTemplate,
		commandTopicTemplate: commandTemplate,
		downlinkTxAckDelay:   cfg.Gateway.DownlinkTxAckDelay,
		devices:              map[lorawan.EUI64]chan gw.DownlinkFrame{},
	}

	downlinkTopic := gateway.commandTopic("down")
	if token := client.Subscribe(downlinkTopic, 1, gateway.handleDownlink); token.Wait() && token.Error() != nil {
		return nil, fmt.Errorf("subscribe downlink topic: %w", token.Error())
	}

	log.Printf("chirpstack-simulator: subscribed gateway_id=%s topic=%s", gateway.gatewayID.String(), downlinkTopic)
	return gateway, nil
}

func (g *Gateway) Close() {
	if g.mqtt == nil {
		return
	}
	g.mqtt.Disconnect(250)
}

func (g *Gateway) RegisterDevice(devEUI lorawan.EUI64, downlinkFrames chan gw.DownlinkFrame) {
	g.deviceMu.Lock()
	defer g.deviceMu.Unlock()
	g.devices[devEUI] = downlinkFrames
}

func (g *Gateway) SendUplinkFrame(pl gw.UplinkFrame) error {
	pl.RxInfo = &gw.UplinkRxInfo{
		GatewayId: g.gatewayID.String(),
		Rssi:      50,
		Snr:       5.5,
		Context:   []byte{0x01, 0x02, 0x03, 0x04},
	}

	b, err := proto.Marshal(&pl)
	if err != nil {
		return fmt.Errorf("marshal uplink frame: %w", err)
	}

	topic := g.eventTopic("up")
	if token := g.mqtt.Publish(topic, 1, false, b); token.Wait() && token.Error() != nil {
		return fmt.Errorf("publish uplink frame: %w", token.Error())
	}

	return nil
}

func (g *Gateway) handleDownlink(_ mqtt.Client, msg mqtt.Message) {
	var frame gw.DownlinkFrame
	if err := proto.Unmarshal(msg.Payload(), &frame); err != nil {
		log.Printf("chirpstack-simulator: unmarshal downlink error: %v", err)
		return
	}

	g.deviceMu.RLock()
	for _, downlinkFrames := range g.devices {
		downlinkFrames <- frame
	}
	g.deviceMu.RUnlock()

	timepkg.Sleep(g.downlinkTxAckDelay)
	ack := gw.DownlinkTxAck{
		GatewayId: frame.GatewayId,
		DownlinkId: frame.DownlinkId,
		Items: []*gw.DownlinkTxAckItem{{Status: gw.TxAckStatus_OK}},
	}

	b, err := proto.Marshal(&ack)
	if err != nil {
		log.Printf("chirpstack-simulator: marshal txack error: %v", err)
		return
	}

	topic := g.eventTopic("ack")
	if token := g.mqtt.Publish(topic, 1, false, b); token.Wait() && token.Error() != nil {
		log.Printf("chirpstack-simulator: publish txack error: %v", token.Error())
	}
	log.Printf("chirpstack-simulator: downlink received gateway_id=%s topic=%s", g.gatewayID.String(), msg.Topic())
}

func (g *Gateway) eventTopic(event string) string {
	return executeTemplate(g.eventTopicTemplate, struct {
		GatewayID string
		Event     string
	}{GatewayID: g.gatewayID.String(), Event: event})
}

func (g *Gateway) commandTopic(command string) string {
	return executeTemplate(g.commandTopicTemplate, struct {
		GatewayID string
		Command   string
	}{GatewayID: g.gatewayID.String(), Command: command})
}

func executeTemplate(t *template.Template, data any) string {
	buf := bytes.NewBuffer(nil)
	if err := t.Execute(buf, data); err != nil {
		panic(err)
	}
	return buf.String()
}
