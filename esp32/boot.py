"""5map ESP32 boot configuration."""
import esp
esp.osdebug(None)  # Suppress OS debug output
import gc
gc.collect()
