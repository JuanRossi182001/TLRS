package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	configPath := flag.String("c", "chirpstack-simulator.toml", "Path to config file")
	flag.Parse()

	cfg, err := LoadConfig(*configPath)
	if err != nil {
		log.Fatalf("load config error: %v", err)
	}

	points, err := BuildScenarioPoints(cfg)
	if err != nil {
		log.Fatalf("build scenario error: %v", err)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	if cfg.Scenario.Duration > 0 {
		ctx, cancel = context.WithTimeout(ctx, cfg.Scenario.Duration)
		defer cancel()
	}

	gateway, err := NewGateway(cfg)
	if err != nil {
		log.Fatalf("gateway init error: %v", err)
	}
	defer gateway.Close()

	device, err := NewSimDevice(cfg, gateway, points)
	if err != nil {
		log.Fatalf("device init error: %v", err)
	}

	log.Printf("chirpstack-simulator: starting fixed device simulation dev_eui=%s gateway_id=%s scenario=%s points=%d",
		cfg.Device.DevEUI.String(),
		cfg.Gateway.ID.String(),
		cfg.Scenario.Name,
		len(points),
	)

	err = device.Run(ctx)
	if err != nil && !errors.Is(err, context.Canceled) && !errors.Is(err, context.DeadlineExceeded) {
		log.Fatalf("simulation error: %v", err)
	}

	if errors.Is(err, context.DeadlineExceeded) {
		log.Printf("chirpstack-simulator: simulation duration reached")
		return
	}

	if err == nil || errors.Is(err, context.Canceled) {
		log.Printf("chirpstack-simulator: simulation stopped")
		return
	}

	log.Printf("chirpstack-simulator: stopped with status=%s", fmt.Sprint(err))
}
