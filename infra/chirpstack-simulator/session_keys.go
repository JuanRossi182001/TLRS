package main

import (
	"crypto/aes"
	"fmt"

	"github.com/brocaar/lorawan"
)

func getAppSKey(optNeg bool, nwkKey lorawan.AES128Key, netID lorawan.NetID, joinEUI lorawan.EUI64, joinNonce lorawan.JoinNonce, devNonce lorawan.DevNonce) (lorawan.AES128Key, error) {
	return getSKey(optNeg, 0x02, nwkKey, netID, joinEUI, joinNonce, devNonce)
}

func getFNwkSIntKey(optNeg bool, nwkKey lorawan.AES128Key, netID lorawan.NetID, joinEUI lorawan.EUI64, joinNonce lorawan.JoinNonce, devNonce lorawan.DevNonce) (lorawan.AES128Key, error) {
	return getSKey(optNeg, 0x01, nwkKey, netID, joinEUI, joinNonce, devNonce)
}

func getSKey(optNeg bool, typ byte, nwkKey lorawan.AES128Key, netID lorawan.NetID, joinEUI lorawan.EUI64, joinNonce lorawan.JoinNonce, devNonce lorawan.DevNonce) (lorawan.AES128Key, error) {
	var key lorawan.AES128Key
	b := make([]byte, 16)
	b[0] = typ

	netIDB, err := netID.MarshalBinary()
	if err != nil {
		return key, err
	}
	joinEUIB, err := joinEUI.MarshalBinary()
	if err != nil {
		return key, err
	}
	joinNonceB, err := joinNonce.MarshalBinary()
	if err != nil {
		return key, err
	}
	devNonceB, err := devNonce.MarshalBinary()
	if err != nil {
		return key, err
	}

	if optNeg {
		copy(b[1:4], joinNonceB)
		copy(b[4:12], joinEUIB)
		copy(b[12:14], devNonceB)
	} else {
		copy(b[1:4], joinNonceB)
		copy(b[4:7], netIDB)
		copy(b[7:9], devNonceB)
	}

	block, err := aes.NewCipher(nwkKey[:])
	if err != nil {
		return key, err
	}
	if block.BlockSize() != len(b) {
		return key, fmt.Errorf("unexpected block-size: %d", block.BlockSize())
	}
	block.Encrypt(key[:], b)

	return key, nil
}
