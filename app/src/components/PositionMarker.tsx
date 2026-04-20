import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated, Easing } from 'react-native';

interface PositionMarkerProps {
  x: number;
  y: number;
  label: string;
  isActive: boolean;
}

const PositionMarker: React.FC<PositionMarkerProps> = ({ x, y, label, isActive }) => {
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (isActive) {
      const animation = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 1.6,
            duration: 1000,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 1000,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
        ])
      );
      animation.start();
      return () => animation.stop();
    } else {
      pulseAnim.setValue(1);
    }
  }, [isActive, pulseAnim]);

  const markerColor = isActive ? '#00d4ff' : '#8892a4';

  return (
    <View style={[styles.wrapper, { left: x - 20, top: y - 20 }]}>
      {isActive && (
        <Animated.View
          style={[
            styles.pulseRing,
            {
              borderColor: '#00d4ff',
              transform: [{ scale: pulseAnim }],
              opacity: pulseAnim.interpolate({
                inputRange: [1, 1.6],
                outputRange: [0.6, 0],
              }),
            },
          ]}
        />
      )}
      <View style={[styles.marker, { backgroundColor: markerColor }]} />
      <Text style={[styles.label, { color: markerColor }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    width: 40,
    alignItems: 'center',
  },
  pulseRing: {
    position: 'absolute',
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 2,
    top: 0,
    alignSelf: 'center',
  },
  marker: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: '#0a0e17',
  },
  label: {
    fontSize: 10,
    fontWeight: '600',
    marginTop: 4,
    textAlign: 'center',
  },
});

export default PositionMarker;
