import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
  Alert,
  Linking,
} from 'react-native';
import { useStore } from '../store';
import { api } from '../services/api';
import type { Session } from '../types';

export function SettingsScreen() {
  const currentSession = useStore((s) => s.currentSession);
  const sessions = useStore((s) => s.sessions);
  const wsConnected = useStore((s) => s.wsConnected);
  const setCurrentSession = useStore((s) => s.setCurrentSession);

  const [pineappleIp, setPineappleIp] = useState<string>('');
  const [apiEndpoint, setApiEndpoint] = useState<string>('api.voicechatbox.com');
  const [wsEndpoint, setWsEndpoint] = useState<string>('');
  const [newSessionName, setNewSessionName] = useState<string>('');
  const [isCreating, setIsCreating] = useState<boolean>(false);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [showSessionPicker, setShowSessionPicker] = useState<boolean>(false);

  const handleCreateSession = useCallback(async () => {
    if (!newSessionName.trim()) {
      Alert.alert('Error', 'Please enter a session name');
      return;
    }

    setIsCreating(true);
    const { data, error } = await api.createSession(newSessionName.trim());

    if (error) {
      Alert.alert('Error', `Failed to create session: ${error}`);
    } else if (data) {
      setCurrentSession(data);
      setNewSessionName('');
      Alert.alert('Success', `Session "${data.name}" created`);
    }
    setIsCreating(false);
  }, [newSessionName, setCurrentSession]);

  const handleExportPdf = useCallback(async () => {
    if (!currentSession) {
      Alert.alert('Error', 'No active session to export');
      return;
    }

    setIsExporting(true);
    try {
      const exportUrl = `https://${apiEndpoint}/api/export/${currentSession.session_id}/pdf`;
      await Linking.openURL(exportUrl);
    } catch (err) {
      Alert.alert('Error', 'Failed to open export link');
    }
    setIsExporting(false);
  }, [currentSession, apiEndpoint]);

  const handleSelectSession = useCallback(
    (session: Session) => {
      setCurrentSession(session);
      setShowSessionPicker(false);
    },
    [setCurrentSession],
  );

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <Text style={styles.title}>Settings</Text>

      <View style={styles.statusRow}>
        <View
          style={[
            styles.statusDot,
            wsConnected ? styles.statusConnected : styles.statusDisconnected,
          ]}
        />
        <Text style={styles.statusText}>
          WebSocket {wsConnected ? 'Connected' : 'Disconnected'}
        </Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Connection</Text>

        <Text style={styles.inputLabel}>Pineapple IP</Text>
        <TextInput
          style={styles.input}
          value={pineappleIp}
          onChangeText={setPineappleIp}
          placeholder="172.16.42.1"
          placeholderTextColor="#4b5563"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="numeric"
        />

        <Text style={styles.inputLabel}>API Endpoint</Text>
        <TextInput
          style={styles.input}
          value={apiEndpoint}
          onChangeText={setApiEndpoint}
          placeholder="api.voicechatbox.com"
          placeholderTextColor="#4b5563"
          autoCapitalize="none"
          autoCorrect={false}
        />

        <Text style={styles.inputLabel}>WebSocket Endpoint</Text>
        <TextInput
          style={styles.input}
          value={wsEndpoint}
          onChangeText={setWsEndpoint}
          placeholder="wss://ws.voicechatbox.com"
          placeholderTextColor="#4b5563"
          autoCapitalize="none"
          autoCorrect={false}
        />
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Sessions</Text>

        <Text style={styles.inputLabel}>New Session Name</Text>
        <TextInput
          style={styles.input}
          value={newSessionName}
          onChangeText={setNewSessionName}
          placeholder="Audit session name"
          placeholderTextColor="#4b5563"
        />

        <TouchableOpacity
          style={[styles.button, isCreating && styles.buttonDisabled]}
          onPress={handleCreateSession}
          disabled={isCreating}
          activeOpacity={0.7}
        >
          <Text style={styles.buttonText}>
            {isCreating ? 'Creating...' : 'New Session'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.pickerButton}
          onPress={() => setShowSessionPicker(!showSessionPicker)}
          activeOpacity={0.7}
        >
          <Text style={styles.pickerButtonText}>
            {currentSession ? currentSession.name : 'Select Session'}
          </Text>
          <Text style={styles.pickerArrow}>
            {showSessionPicker ? '▲' : '▼'}
          </Text>
        </TouchableOpacity>

        {showSessionPicker && (
          <View style={styles.pickerDropdown}>
            {sessions.length === 0 ? (
              <Text style={styles.pickerEmpty}>No sessions available</Text>
            ) : (
              sessions.map((session) => (
                <TouchableOpacity
                  key={session.session_id}
                  style={[
                    styles.pickerItem,
                    currentSession?.session_id === session.session_id &&
                      styles.pickerItemActive,
                  ]}
                  onPress={() => handleSelectSession(session)}
                  activeOpacity={0.7}
                >
                  <Text style={styles.pickerItemName}>{session.name}</Text>
                  <Text style={styles.pickerItemMeta}>
                    {session.status} · {session.device_count} devices
                  </Text>
                </TouchableOpacity>
              ))
            )}
          </View>
        )}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Export</Text>

        <TouchableOpacity
          style={[
            styles.button,
            styles.buttonExport,
            (isExporting || !currentSession) && styles.buttonDisabled,
          ]}
          onPress={handleExportPdf}
          disabled={isExporting || !currentSession}
          activeOpacity={0.7}
        >
          <Text style={styles.buttonText}>
            {isExporting ? 'Generating...' : 'Export PDF'}
          </Text>
        </TouchableOpacity>

        {!currentSession && (
          <Text style={styles.hintText}>
            Select or create a session to enable export
          </Text>
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0e17',
  },
  content: {
    padding: 16,
    paddingBottom: 48,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#e8eaed',
    marginBottom: 12,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 24,
    backgroundColor: '#131a2b',
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1e2a42',
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 10,
  },
  statusConnected: {
    backgroundColor: '#2ed573',
  },
  statusDisconnected: {
    backgroundColor: '#ff4757',
  },
  statusText: {
    fontSize: 14,
    color: '#e8eaed',
    fontWeight: '500',
  },
  section: {
    marginBottom: 28,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#00d4ff',
    marginBottom: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  inputLabel: {
    fontSize: 13,
    color: '#9ca3af',
    marginBottom: 6,
    marginTop: 12,
  },
  input: {
    backgroundColor: '#131a2b',
    borderWidth: 1,
    borderColor: '#1e2a42',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: '#e8eaed',
  },
  button: {
    backgroundColor: '#00d4ff',
    paddingVertical: 14,
    borderRadius: 10,
    alignItems: 'center',
    marginTop: 16,
  },
  buttonExport: {
    backgroundColor: '#2ed573',
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonText: {
    fontSize: 15,
    fontWeight: '700',
    color: '#0a0e17',
  },
  pickerButton: {
    backgroundColor: '#131a2b',
    borderWidth: 1,
    borderColor: '#1e2a42',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 14,
    marginTop: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  pickerButtonText: {
    fontSize: 15,
    color: '#e8eaed',
  },
  pickerArrow: {
    fontSize: 12,
    color: '#6b7280',
  },
  pickerDropdown: {
    backgroundColor: '#131a2b',
    borderWidth: 1,
    borderColor: '#1e2a42',
    borderRadius: 10,
    marginTop: 4,
    overflow: 'hidden',
  },
  pickerEmpty: {
    padding: 14,
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
  },
  pickerItem: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1e2a42',
  },
  pickerItemActive: {
    backgroundColor: '#00d4ff11',
  },
  pickerItemName: {
    fontSize: 14,
    color: '#e8eaed',
    fontWeight: '500',
  },
  pickerItemMeta: {
    fontSize: 12,
    color: '#6b7280',
    marginTop: 2,
  },
  hintText: {
    fontSize: 12,
    color: '#6b7280',
    marginTop: 8,
    textAlign: 'center',
  },
});
