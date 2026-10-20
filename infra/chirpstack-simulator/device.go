package main

import (
	"context"
	crand "crypto/rand"
	"encoding/binary"
	"fmt"
	"log"
	"sync"
	timepkg "time"

	"github.com/brocaar/lorawan"
	"github.com/chirpstack/chirpstack/api/go/v4/gw"
)

type deviceState int

const (
	deviceStateOTAA deviceState = iota
	deviceStateActivated
)

type SimDevice struct {
	mu sync.RWMutex

	devEUI         lorawan.EUI64
	joinEUI        lorawan.EUI64
	appKey         lorawan.AES128Key
	uplinkInterval timepkg.Duration
	confirmedUplink bool
	fPort          uint8
	frequency      int
	bandwidth      int
	spreadingFactor int
	otaaDelay      timepkg.Duration
	gateway        *Gateway
	downlinkFrames chan gw.DownlinkFrame
	outboundUplinks chan lorawan.PHYPayload
	points         []TelemetryPoint
	nextPointIndex int
	state          deviceState
	devNonce       lorawan.DevNonce
	devAddr        lorawan.DevAddr
	fCntUp         uint32
	fCntDown       uint32
	appSKey        lorawan.AES128Key
	nwkSKey        lorawan.AES128Key
	pendingAck     bool
	ackDelay       timepkg.Duration
}

func NewSimDevice(cfg Config, gateway *Gateway, points []TelemetryPoint) (*SimDevice, error) {
	if len(points) == 0 {
		return nil, fmt.Errorf("at least one telemetry point is required")
	}

	device := &SimDevice{
		devEUI:          cfg.Device.DevEUI,
		joinEUI:         cfg.Device.JoinEUI,
		appKey:          cfg.Device.AppKey,
		uplinkInterval:  cfg.Device.UplinkInterval,
		confirmedUplink: cfg.Device.ConfirmedUplink,
		fPort:           cfg.Device.FPort,
		frequency:       cfg.Device.Frequency,
		bandwidth:       cfg.Device.Bandwidth,
		spreadingFactor: cfg.Device.SpreadingFactor,
		otaaDelay:       cfg.Device.OTAADelay,
		gateway:         gateway,
		downlinkFrames:  make(chan gw.DownlinkFrame, 100),
		outboundUplinks: make(chan lorawan.PHYPayload, 100),
		points:          points,
		state:           deviceStateOTAA,
		ackDelay:        cfg.Gateway.DownlinkTxAckDelay,
	}

	gateway.RegisterDevice(device.devEUI, device.downlinkFrames)
	return device, nil
}

func (d *SimDevice) Run(ctx context.Context) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	var wg sync.WaitGroup
	wg.Add(3)

	var runErr error
	var once sync.Once
	setErr := func(err error) {
		if err == nil {
			return
		}
		once.Do(func() {
			runErr = err
			cancel()
		})
	}

	go func() {
		defer wg.Done()
		setErr(d.uplinkLoop(ctx))
	}()

	go func() {
		defer wg.Done()
		setErr(d.downlinkLoop(ctx))
	}()

	go func() {
		defer wg.Done()
		setErr(d.uplinkSenderLoop(ctx))
	}()

	wg.Wait()
	if runErr != nil {
		return runErr
	}
	return ctx.Err()
}

func (d *SimDevice) uplinkLoop(ctx context.Context) error {
	if d.otaaDelay > 0 {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timepkg.After(d.otaaDelay):
		}
	}

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		if d.getState() == deviceStateOTAA {
			if err := d.joinRequest(); err != nil {
				return err
			}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-timepkg.After(6 * timepkg.Second):
			}
			continue
		}

		point := d.nextPoint()
		ack := d.consumePendingAck()
		if err := d.sendDataUplink(point, ack); err != nil {
			return err
		}

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timepkg.After(d.uplinkInterval):
		}
	}
}

func (d *SimDevice) downlinkLoop(ctx context.Context) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case frame := <-d.downlinkFrames:
			for _, item := range frame.Items {
				var phy lorawan.PHYPayload
				if err := phy.UnmarshalBinary(item.PhyPayload); err != nil {
					return fmt.Errorf("unmarshal downlink phypayload: %w", err)
				}

				switch phy.MHDR.MType {
				case lorawan.JoinAccept:
					if err := d.joinAccept(phy); err != nil {
						return err
					}
				case lorawan.UnconfirmedDataDown, lorawan.ConfirmedDataDown:
					if err := d.downlinkData(ctx, phy); err != nil {
						return err
					}
				}
				break
			}
		}
	}
}

func (d *SimDevice) joinRequest() error {
	phy := lorawan.PHYPayload{
		MHDR: lorawan.MHDR{MType: lorawan.JoinRequest, Major: lorawan.LoRaWANR1},
		MACPayload: &lorawan.JoinRequestPayload{
			DevEUI: d.devEUI,
			JoinEUI: d.joinEUI,
			DevNonce: d.nextDevNonce(),
		},
	}

	if err := phy.SetUplinkJoinMIC(d.appKey); err != nil {
		return fmt.Errorf("set uplink join mic: %w", err)
	}

	log.Printf("chirpstack-simulator: sending join-request dev_eui=%s", d.devEUI.String())
	return d.enqueueUplink(phy)
}

func (d *SimDevice) joinAccept(phy lorawan.PHYPayload) error {
	if err := phy.DecryptJoinAcceptPayload(d.appKey); err != nil {
		return fmt.Errorf("decrypt join-accept payload: %w", err)
	}

	ok, err := phy.ValidateDownlinkJoinMIC(lorawan.JoinRequestType, d.joinEUI, d.devNonce, d.appKey)
	if err != nil {
		return fmt.Errorf("validate join-accept mic: %w", err)
	}
	if !ok {
		return fmt.Errorf("invalid join-accept MIC")
	}

	jaPL, ok := phy.MACPayload.(*lorawan.JoinAcceptPayload)
	if !ok {
		return fmt.Errorf("expected JoinAcceptPayload, got %T", phy.MACPayload)
	}

	appSKey, err := getAppSKey(jaPL.DLSettings.OptNeg, d.appKey, jaPL.HomeNetID, d.joinEUI, jaPL.JoinNonce, d.devNonce)
	if err != nil {
		return fmt.Errorf("derive app_s_key: %w", err)
	}
	nwkSKey, err := getFNwkSIntKey(jaPL.DLSettings.OptNeg, d.appKey, jaPL.HomeNetID, d.joinEUI, jaPL.JoinNonce, d.devNonce)
	if err != nil {
		return fmt.Errorf("derive nwk_s_key: %w", err)
	}

	d.mu.Lock()
	d.appSKey = appSKey
	d.nwkSKey = nwkSKey
	d.devAddr = jaPL.DevAddr
	d.state = deviceStateActivated
	d.mu.Unlock()

	log.Printf("chirpstack-simulator: device activated dev_eui=%s dev_addr=%s", d.devEUI.String(), d.devAddr.String())
	return nil
}

func (d *SimDevice) downlinkData(ctx context.Context, phy lorawan.PHYPayload) error {
	ok, err := phy.ValidateDownlinkDataMIC(lorawan.LoRaWAN1_0, 0, d.nwkSKey)
	if err != nil {
		return fmt.Errorf("validate downlink data MIC: %w", err)
	}
	if !ok {
		return fmt.Errorf("invalid downlink data MIC")
	}

	macPL, ok := phy.MACPayload.(*lorawan.MACPayload)
	if !ok {
		return fmt.Errorf("expected MACPayload, got %T", phy.MACPayload)
	}

	gap := uint32(uint16(macPL.FHDR.FCnt) - uint16(d.fCntDown%(1<<16)))
	d.fCntDown = d.fCntDown + gap

	confirmed := phy.MHDR.MType == lorawan.ConfirmedDataDown
	if confirmed {
		d.setPendingAck(true)
	}

	var payload []byte
	var fPort uint8
	if macPL.FPort != nil {
		fPort = *macPL.FPort
	}

	if fPort != 0 {
		if err := phy.DecryptFRMPayload(d.appSKey); err != nil {
			return fmt.Errorf("decrypt downlink frm payload: %w", err)
		}
		if len(macPL.FRMPayload) > 0 {
			dataPayload, ok := macPL.FRMPayload[0].(*lorawan.DataPayload)
			if !ok {
				return fmt.Errorf("expected DataPayload, got %T", macPL.FRMPayload[0])
			}
			payload = dataPayload.Bytes
		}
	}

	log.Printf("chirpstack-simulator: downlink received dev_eui=%s confirmed=%t ack=%t f_port=%d bytes=%d",
		d.devEUI.String(),
		confirmed,
		macPL.FHDR.FCtrl.ACK,
		fPort,
		len(payload),
	)

	if len(payload) == 0 {
		return nil
	}

	decodedCommand, err := DecodeCommandPayload(payload)
	if err != nil {
		log.Printf("chirpstack-simulator: could not decode command payload: %v", err)
		commandSeq, seqErr := ExtractCommandSeq(payload)
		if seqErr == nil {
			go func() {
				select {
				case <-ctx.Done():
					return
				case <-timepkg.After(d.ackDelay):
				}
				if err := d.sendApplicationAck(commandSeq, commandAckStatusFailed, commandAckErrorInvalidPayload); err != nil {
					log.Printf("chirpstack-simulator: invalid payload ack error: %v", err)
				}
			}()
		}
		return nil
	}

	go func() {
		select {
		case <-ctx.Done():
			return
		case <-timepkg.After(d.ackDelay):
		}
		if err := d.sendApplicationAck(decodedCommand.CommandSeq, commandAckStatusExecuted, commandAckErrorNone); err != nil {
			log.Printf("chirpstack-simulator: application ack error: %v", err)
		}
	}()

	return nil
}

func (d *SimDevice) sendDataUplink(point TelemetryPoint, ack bool) error {
	payload := EncodeLocationPayload(point)
	return d.sendDataFrame(d.fPort, payload, d.confirmedUplink, ack)
}

func (d *SimDevice) sendApplicationAck(commandSeq uint16, statusCode uint8, errorCode uint8) error {
	payload := EncodeCommandAckPayload(commandSeq, statusCode, errorCode)
	ack := d.consumePendingAck()
	return d.sendDataFrame(20, payload, false, ack)
}

func (d *SimDevice) sendDataFrame(fPort uint8, payload []byte, confirmed bool, ack bool) error {
	mType := lorawan.UnconfirmedDataUp
	if confirmed {
		mType = lorawan.ConfirmedDataUp
	}

	fcnt := d.nextFCntUp()
	phy := lorawan.PHYPayload{
		MHDR: lorawan.MHDR{MType: mType, Major: lorawan.LoRaWANR1},
		MACPayload: &lorawan.MACPayload{
			FHDR: lorawan.FHDR{
				DevAddr: d.devAddr,
				FCnt: fcnt,
				FCtrl: lorawan.FCtrl{ACK: ack},
			},
			FPort: &fPort,
			FRMPayload: []lorawan.Payload{&lorawan.DataPayload{Bytes: payload}},
		},
	}

	if err := phy.EncryptFRMPayload(d.appSKey); err != nil {
		return fmt.Errorf("encrypt frm payload: %w", err)
	}
	if err := phy.SetUplinkDataMIC(lorawan.LoRaWAN1_0, 0, 0, 0, d.nwkSKey, d.nwkSKey); err != nil {
		return fmt.Errorf("set uplink data MIC: %w", err)
	}

	return d.enqueueUplink(phy)
}

func (d *SimDevice) uplinkSenderLoop(ctx context.Context) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case phy := <-d.outboundUplinks:
			if err := d.publishUplink(phy); err != nil {
				return err
			}
		}
	}
}

func (d *SimDevice) enqueueUplink(phy lorawan.PHYPayload) error {
	d.outboundUplinks <- phy
	return nil
}

func (d *SimDevice) publishUplink(phy lorawan.PHYPayload) error {
	b, err := phy.MarshalBinary()
	if err != nil {
		return fmt.Errorf("marshal phypayload: %w", err)
	}

	frame := gw.UplinkFrame{
		PhyPayload: b,
		TxInfo: &gw.UplinkTxInfo{
			Frequency: uint32(d.frequency),
			Modulation: &gw.Modulation{
				Parameters: &gw.Modulation_Lora{
					Lora: &gw.LoraModulationInfo{
						Bandwidth:       uint32(d.bandwidth),
						SpreadingFactor: uint32(d.spreadingFactor),
						CodeRate:        gw.CodeRate_CR_4_5,
					},
				},
			},
		},
	}

	return d.gateway.SendUplinkFrame(frame)
}

func (d *SimDevice) nextDevNonce() lorawan.DevNonce {
	b := make([]byte, 2)
	_, _ = crand.Read(b)
	d.devNonce = lorawan.DevNonce(binary.BigEndian.Uint16(b))
	return d.devNonce
}

func (d *SimDevice) nextFCntUp() uint32 {
	d.mu.Lock()
	defer d.mu.Unlock()
	fCnt := d.fCntUp
	d.fCntUp++
	return fCnt
}

func (d *SimDevice) getState() deviceState {
	d.mu.RLock()
	defer d.mu.RUnlock()
	return d.state
}

func (d *SimDevice) setPendingAck(value bool) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.pendingAck = value
}

func (d *SimDevice) consumePendingAck() bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	value := d.pendingAck
	d.pendingAck = false
	return value
}

func (d *SimDevice) nextPoint() TelemetryPoint {
	d.mu.Lock()
	defer d.mu.Unlock()
	point := d.points[d.nextPointIndex%len(d.points)]
	d.nextPointIndex++
	return point
}
