#!/usr/bin/env python3
"""Example usage of the enhanced front detection system with classification and tracking.

This script demonstrates how to use the new features:
1. Front type classification (cold/warm/occluded/stationary)
2. Temporal tracking across time steps
3. Frontogenesis/frontolysis detection
4. Nowcasting of front positions
"""

import numpy as np
import front_engine
import front_type_classification as ftc
import front_tracking as ft


def example_single_timestep():
    """Example: Detect and classify fronts at a single time step."""
    
    # Load your ICON-2I data
    # theta_w: wet-bulb potential temperature (K)
    # u_wind, v_wind: wind components (m/s)
    # pressure: mean sea level pressure (hPa)
    # longitudes, latitudes: grid coordinates
    
    # For this example, we'll use synthetic data
    n_lon, n_lat = 100, 80
    longitudes = np.linspace(5.0, 20.0, n_lon)
    latitudes = np.linspace(35.0, 48.0, n_lat)
    
    # Create synthetic theta_w with a frontal zone
    lon_grid, lat_grid = np.meshgrid(longitudes, latitudes)
    theta_w = 290.0 + 5.0 * np.tanh((lat_grid - 42.0) / 2.0)
    
    # Synthetic wind (geostrophic approximation)
    u_wind = 10.0 * np.ones_like(theta_w)
    v_wind = -5.0 * np.ones_like(theta_w)
    
    # Synthetic pressure
    pressure = 1013.0 - 5.0 * np.exp(-((lat_grid - 42.0)**2) / 10.0)
    
    # Detect and classify fronts
    candidates = front_engine.detect_fronts_with_classification(
        theta_w, u_wind, v_wind,
        longitudes, latitudes,
        pressure=pressure,
    )
    
    print(f"Detected {len(candidates)} fronts:")
    for i, front in enumerate(candidates):
        front_type = front.get("frontType", "unknown")
        confidence = front.get("frontTypeConfidence", 0.0)
        length = front.get("lengthKm", 0)
        
        print(f"\nFront {i+1}:")
        print(f"  Type: {front_type} (confidence: {confidence:.2f})")
        print(f"  Length: {length:.1f} km")
        
        # Get visualization style
        style = ftc.get_front_style(front_type)
        print(f"  Color: {style['color']}")
        print(f"  Line width: {style['lineWidth']}")
        
        # Print diagnostics
        diagnostics = front.get("frontTypeDiagnostics", {})
        if "medianThermalAdvectionK3h" in diagnostics:
            advection = diagnostics["medianThermalAdvectionK3h"]
            print(f"  Thermal advection: {advection:.2f} K/3h")
        if "frontSpeedKmh" in diagnostics:
            speed = diagnostics["frontSpeedKmh"]
            print(f"  Speed: {speed:.1f} km/h")


def example_temporal_tracking():
    """Example: Track fronts across multiple time steps."""
    
    # Simulate 4 time steps (12 hours total, 3h apart)
    n_time_steps = 4
    n_lon, n_lat = 100, 80
    longitudes = np.linspace(5.0, 20.0, n_lon)
    latitudes = np.linspace(35.0, 48.0, n_lat)
    
    fronts_by_time = []
    
    for t in range(n_time_steps):
        # Front moves northward over time
        lat_grid, lon_grid = np.meshgrid(latitudes, longitudes, indexing='ij')
        front_lat = 40.0 + t * 0.5  # Front moves 0.5 deg per step
        
        theta_w = 290.0 + 5.0 * np.tanh((lat_grid - front_lat) / 2.0)
        u_wind = 10.0 * np.ones_like(theta_w)
        v_wind = -5.0 * np.ones_like(theta_w)
        pressure = 1013.0 - 5.0 * np.exp(-((lat_grid - front_lat)**2) / 10.0)
        
        # Detect fronts at this time step
        candidates = front_engine.detect_fronts_with_classification(
            theta_w, u_wind, v_wind,
            longitudes, latitudes,
            pressure=pressure,
        )
        
        fronts_by_time.append(candidates)
        print(f"Time step {t}: detected {len(candidates)} fronts")
    
    # Track fronts across time
    tracking_result = front_engine.track_fronts_across_time(
        fronts_by_time, longitudes, latitudes,
        dt_hours=3.0,
    )
    
    stats = tracking_result["statistics"]
    print(f"\nTracking statistics:")
    print(f"  Total unique tracks: {stats['total_tracks']}")
    print(f"  Mean track length: {stats['mean_track_length']} time steps")
    print(f"  Frontogenesis events: {stats['frontogenesis_count']}")
    print(f"  Frontolysis events: {stats['frontolysis_count']}")
    
    # Print frontogenesis events
    events = tracking_result["frontogenesis_events"]
    for event in events[:5]:  # Show first 5 events
        print(f"\nEvent: {event['event']}")
        print(f"  Track ID: {event['trackId']}")
        print(f"  Length change: {event['lengthChangePercent']:.1f}%")
        print(f"  Confidence change: {event['confidenceChange']:.3f}")


def example_nowcasting():
    """Example: Generate nowcast of front positions."""
    
    # Detect current fronts
    n_lon, n_lat = 100, 80
    longitudes = np.linspace(5.0, 20.0, n_lon)
    latitudes = np.linspace(35.0, 48.0, n_lat)
    
    lat_grid, lon_grid = np.meshgrid(latitudes, longitudes, indexing='ij')
    theta_w = 290.0 + 5.0 * np.tanh((lat_grid - 42.0) / 2.0)
    u_wind = 10.0 * np.ones_like(theta_w)
    v_wind = -5.0 * np.ones_like(theta_w)
    pressure = 1013.0 - 5.0 * np.exp(-((lat_grid - 42.0)**2) / 10.0)
    
    current_fronts = front_engine.detect_fronts_with_classification(
        theta_w, u_wind, v_wind,
        longitudes, latitudes,
        pressure=pressure,
    )
    
    # Generate 6-hour nowcast
    nowcast = front_engine.nowcast_fronts(current_fronts, forecast_hours=6.0)
    
    print(f"\nNowcast generated for {len(nowcast)} fronts:")
    for i, forecast in enumerate(nowcast):
        print(f"\nFront {i+1}:")
        print(f"  Type: {forecast['frontType']}")
        print(f"  Speed: {forecast['speedKmh']:.1f} km/h")
        print(f"  Direction: {forecast['directionDeg']:.1f} deg")
        print(f"  Current position: {len(forecast['current'])} vertices")
        print(f"  Forecast position: {len(forecast['forecast'])} vertices")


def example_visualization_style():
    """Example: Get visualization styles for different front types."""
    
    front_types = ["cold", "warm", "occluded", "stationary", "unclassified"]
    
    print("\nVisualization styles for front types:")
    print("=" * 60)
    
    for front_type in front_types:
        style = ftc.get_front_style(front_type)
        print(f"\n{front_type.upper()}:")
        print(f"  Color: {style['color']}")
        print(f"  Symbol: {style['symbol']}")
        print(f"  Line width: {style['lineWidth']}")
        if style['dashArray']:
            print(f"  Dash pattern: {style['dashArray']}")


if __name__ == "__main__":
    print("=" * 60)
    print("FRONT DETECTION SYSTEM - USAGE EXAMPLES")
    print("=" * 60)
    
    print("\n" + "=" * 60)
    print("Example 1: Single time step detection and classification")
    print("=" * 60)
    example_single_timestep()
    
    print("\n" + "=" * 60)
    print("Example 2: Temporal tracking across time steps")
    print("=" * 60)
    example_temporal_tracking()
    
    print("\n" + "=" * 60)
    print("Example 3: Nowcasting front positions")
    print("=" * 60)
    example_nowcasting()
    
    print("\n" + "=" * 60)
    print("Example 4: Visualization styles")
    print("=" * 60)
    example_visualization_style()
    
    print("\n" + "=" * 60)
    print("All examples completed successfully!")
    print("=" * 60)
