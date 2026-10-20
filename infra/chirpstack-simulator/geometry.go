package main

import (
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"math"
	"math/rand"
)

type Point struct {
	Lng float64 `json:"lng"`
	Lat float64 `json:"lat"`
}

type TelemetryPoint struct {
	Lng            float64
	Lat            float64
	AltitudeMeters float64
	AccuracyMeters float64
	BatteryPct     uint8
	Label          string
}

var defaultStaticPoints = []TelemetryPoint{
	{Lat: -33.3012, Lng: -66.3371, AltitudeMeters: 520.4, AccuracyMeters: 4.8, BatteryPct: 87, Label: "static-1"},
	{Lat: -33.30105, Lng: -66.33685, AltitudeMeters: 521.0, AccuracyMeters: 4.6, BatteryPct: 86, Label: "static-2"},
	{Lat: -33.3009, Lng: -66.33655, AltitudeMeters: 521.7, AccuracyMeters: 4.9, BatteryPct: 85, Label: "static-3"},
}

func BuildScenarioPoints(cfg Config) ([]TelemetryPoint, error) {
	if cfg.Scenario.Name == "static" {
		return defaultStaticPoints, nil
	}

	if cfg.Scenario.ShapeHex == "" {
		return nil, fmt.Errorf("scenario.shape_hex is required for non-static scenarios")
	}

	rings, err := readMultiPolygonEWKB(cfg.Scenario.ShapeHex)
	if err != nil {
		return nil, err
	}
	if len(rings) == 0 || len(rings[0]) == 0 {
		return nil, fmt.Errorf("shape_hex did not contain a valid polygon")
	}

	outerRing := rings[0][0]
	center := polygonCentroid(outerRing)
	boundary := farthestPoint(center, outerRing[:len(outerRing)-1])

	type routePoint struct {
		ratio    float64
		accuracy float64
		label    string
	}

	var route []routePoint
	switch cfg.Scenario.Name {
	case "inside-outside":
		route = []routePoint{{0.20, 4.8, "inside"}, {0.72, 4.6, "near-limit"}, {1.18, 4.9, "outside"}}
	case "outside-only":
		route = []routePoint{{1.10, 4.8, "outside"}, {1.18, 4.6, "outside"}, {1.26, 4.9, "outside"}}
	default:
		return nil, fmt.Errorf("unsupported scenario: %s", cfg.Scenario.Name)
	}

	points := make([]TelemetryPoint, 0, len(route))
	for i, rp := range route {
		point := jitter(interpolate(center, boundary, rp.ratio), cfg.Scenario.JitterMeters)
		points = append(points, TelemetryPoint{
			Lat:            point.Lat,
			Lng:            point.Lng,
			AltitudeMeters: cfg.Scenario.AltitudeMeters + (float64(i) * 0.5),
			AccuracyMeters: rp.accuracy,
			BatteryPct:     uint8(maxInt(cfg.Scenario.BatteryStart-i, 0)),
			Label:          rp.label,
		})
	}

	return points, nil
}

func readMultiPolygonEWKB(hexValue string) ([][][]Point, error) {
	data, err := hex.DecodeString(removeWhitespace(hexValue))
	if err != nil {
		return nil, fmt.Errorf("decode ewkb hex: %w", err)
	}

	reader := &ewkbReader{data: data}
	return reader.readMultiPolygon()
}

type ewkbReader struct {
	data   []byte
	offset int
}

func (r *ewkbReader) readMultiPolygon() ([][][]Point, error) {
	byteOrder, geometryType, err := r.readHeader()
	if err != nil {
		return nil, err
	}
	endian := endianForByteOrder(byteOrder)

	hasSRID := (geometryType & 0x20000000) != 0
	baseType := geometryType & 0x000000FF
	if baseType != 6 {
		return nil, fmt.Errorf("the provided shape must be an EWKB MultiPolygon")
	}

	if hasSRID {
		if _, err := r.readUint32(endian); err != nil {
			return nil, err
		}
	}

	polygonCount, err := r.readUint32(endian)
	if err != nil {
		return nil, err
	}

	polygons := make([][][]Point, 0, polygonCount)
	for i := uint32(0); i < polygonCount; i++ {
		polygon, err := r.readPolygon()
		if err != nil {
			return nil, err
		}
		polygons = append(polygons, polygon)
	}

	return polygons, nil
}

func (r *ewkbReader) readPolygon() ([][]Point, error) {
	byteOrder, geometryType, err := r.readHeader()
	if err != nil {
		return nil, err
	}
	endian := endianForByteOrder(byteOrder)

	baseType := geometryType & 0x000000FF
	if baseType != 3 {
		return nil, fmt.Errorf("expected Polygon inside MultiPolygon EWKB")
	}

	ringCount, err := r.readUint32(endian)
	if err != nil {
		return nil, err
	}

	rings := make([][]Point, 0, ringCount)
	for i := uint32(0); i < ringCount; i++ {
		pointCount, err := r.readUint32(endian)
		if err != nil {
			return nil, err
		}

		ring := make([]Point, 0, pointCount)
		for j := uint32(0); j < pointCount; j++ {
			lng, err := r.readFloat64(endian)
			if err != nil {
				return nil, err
			}
			lat, err := r.readFloat64(endian)
			if err != nil {
				return nil, err
			}
			ring = append(ring, Point{Lng: lng, Lat: lat})
		}
		rings = append(rings, ring)
	}

	return rings, nil
}

func (r *ewkbReader) readHeader() (byte, uint32, error) {
	if r.offset >= len(r.data) {
		return 0, 0, fmt.Errorf("unexpected end of EWKB")
	}
	byteOrder := r.data[r.offset]
	r.offset++
	endian := endianForByteOrder(byteOrder)
	geometryType, err := r.readUint32(endian)
	return byteOrder, geometryType, err
}

func (r *ewkbReader) readUint32(endian binary.ByteOrder) (uint32, error) {
	if r.offset+4 > len(r.data) {
		return 0, fmt.Errorf("unexpected end of EWKB while reading uint32")
	}
	value := endian.Uint32(r.data[r.offset : r.offset+4])
	r.offset += 4
	return value, nil
}

func (r *ewkbReader) readFloat64(endian binary.ByteOrder) (float64, error) {
	if r.offset+8 > len(r.data) {
		return 0, fmt.Errorf("unexpected end of EWKB while reading float64")
	}
	bits := endian.Uint64(r.data[r.offset : r.offset+8])
	r.offset += 8
	return math.Float64frombits(bits), nil
}

func endianForByteOrder(byteOrder byte) binary.ByteOrder {
	if byteOrder == 0 {
		return binary.BigEndian
	}
	return binary.LittleEndian
}

func polygonCentroid(ring []Point) Point {
	points := ring
	if len(ring) > 1 && ring[0] == ring[len(ring)-1] {
		points = ring[:len(ring)-1]
	}

	var signedArea float64
	var centroidLng float64
	var centroidLat float64

	for i, current := range points {
		next := points[(i+1)%len(points)]
		cross := current.Lng*next.Lat - next.Lng*current.Lat
		signedArea += cross
		centroidLng += (current.Lng + next.Lng) * cross
		centroidLat += (current.Lat + next.Lat) * cross
	}

	signedArea *= 0.5
	if math.Abs(signedArea) < 1e-9 {
		var lngSum, latSum float64
		for _, point := range points {
			lngSum += point.Lng
			latSum += point.Lat
		}
		return Point{Lng: lngSum / float64(len(points)), Lat: latSum / float64(len(points))}
	}

	return Point{
		Lng: centroidLng / (6 * signedArea),
		Lat: centroidLat / (6 * signedArea),
	}
}

func farthestPoint(origin Point, points []Point) Point {
	best := points[0]
	bestDistance := distanceDegrees(origin, best)
	for _, point := range points[1:] {
		distance := distanceDegrees(origin, point)
		if distance > bestDistance {
			best = point
			bestDistance = distance
		}
	}
	return best
}

func interpolate(start, end Point, ratio float64) Point {
	return Point{
		Lng: start.Lng + ((end.Lng - start.Lng) * ratio),
		Lat: start.Lat + ((end.Lat - start.Lat) * ratio),
	}
}

func jitter(point Point, jitterMeters float64) Point {
	if jitterMeters <= 0 {
		return point
	}

	metersPerDegreeLat := 111_320.0
	metersPerDegreeLng := metersPerDegreeLat * math.Cos(point.Lat*math.Pi/180)
	return Point{
		Lng: point.Lng + (randomBetween(-jitterMeters, jitterMeters) / metersPerDegreeLng),
		Lat: point.Lat + (randomBetween(-jitterMeters, jitterMeters) / metersPerDegreeLat),
	}
}

func distanceDegrees(first, second Point) float64 {
	return math.Hypot(first.Lng-second.Lng, first.Lat-second.Lat)
}

func randomBetween(min, max float64) float64 {
	return min + (rand.Float64() * (max - min))
}

func removeWhitespace(value string) string {
	result := make([]rune, 0, len(value))
	for _, r := range value {
		if r != ' ' && r != '\n' && r != '\t' && r != '\r' {
			result = append(result, r)
		}
	}
	return string(result)
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
