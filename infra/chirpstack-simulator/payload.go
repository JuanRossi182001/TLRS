package main

import (
	"encoding/binary"
	"fmt"
	"math"
)

const (
	protocolVersionV1               = 1
	locationMessageType             = 1
	statusMessageType               = 2
	gpsFixNoFix                     = 0
	gpsFixGPS                       = 1
	commandTypeSetReportInterval    = 1
	commandTypeWarningSound         = 2
	commandTypeStopCorrection       = 3
	commandTypeRequestStatus        = 4
	commandAckStatusExecuted        = 1
	commandAckStatusFailed          = 3
	commandAckErrorNone             = 0
	commandAckErrorInvalidPayload   = 2
)

type DecodedCommandPayload struct {
	CommandType uint8
	CommandSeq  uint16
	Flags       uint8
}

func EncodeLocationPayload(point TelemetryPoint) []byte {
	payload := make([]byte, 15)
	payload[0] = protocolVersionV1
	payload[1] = locationMessageType
	binary.BigEndian.PutUint32(payload[2:6], uint32(int32(math.Round(point.Lat*10_000_000))))
	binary.BigEndian.PutUint32(payload[6:10], uint32(int32(math.Round(point.Lng*10_000_000))))
	binary.BigEndian.PutUint16(payload[10:12], uint16(int16(math.Round(point.AltitudeMeters))))
	payload[12] = uint8(math.Max(0, math.Min(255, math.Round(point.AccuracyMeters))))
	payload[13] = point.BatteryPct
	payload[14] = gpsFixGPS
	return payload
}

func EncodeCommandAckPayload(commandSeq uint16, statusCode uint8, errorCode uint8) []byte {
	payload := make([]byte, 5)
	payload[0] = protocolVersionV1
	binary.BigEndian.PutUint16(payload[1:3], commandSeq)
	payload[3] = statusCode
	payload[4] = errorCode
	return payload
	}

func DecodeCommandPayload(payload []byte) (DecodedCommandPayload, error) {
	if len(payload) < 5 {
		return DecodedCommandPayload{}, fmt.Errorf("command payload too short")
	}

	decoded := DecodedCommandPayload{
		CommandType: payload[1],
		CommandSeq:  binary.BigEndian.Uint16(payload[2:4]),
		Flags:       payload[4],
	}
	if payload[0] != protocolVersionV1 {
		return DecodedCommandPayload{}, fmt.Errorf("unsupported command version: %d", payload[0])
	}
	if decoded.CommandSeq == 0 {
		return DecodedCommandPayload{}, fmt.Errorf("invalid command_seq 0")
	}

	switch decoded.CommandType {
	case commandTypeSetReportInterval:
		if len(payload) != 7 {
			return DecodedCommandPayload{}, fmt.Errorf("invalid SET_REPORT_INTERVAL payload length")
		}
	case commandTypeWarningSound:
		if len(payload) != 6 {
			return DecodedCommandPayload{}, fmt.Errorf("invalid WARNING_SOUND payload length")
		}
	case commandTypeStopCorrection, commandTypeRequestStatus:
		if len(payload) != 5 {
			return DecodedCommandPayload{}, fmt.Errorf("invalid zero-parameter command payload length")
		}
	default:
		return DecodedCommandPayload{}, fmt.Errorf("unknown command type: %d", decoded.CommandType)
	}

	return decoded, nil
}

func ExtractCommandSeq(payload []byte) (uint16, error) {
	if len(payload) < 4 {
		return 0, fmt.Errorf("command payload too short for command_seq")
	}
	commandSeq := binary.BigEndian.Uint16(payload[2:4])
	if commandSeq == 0 {
		return 0, fmt.Errorf("invalid command_seq 0")
	}
	return commandSeq, nil
}
