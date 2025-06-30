import time
import board
import adafruit_dht
import busio
import adafruit_ltr390

i2c = busio.I2C(board.SCL, board.SDA)
ltr = adafruit_ltr390.LTR390(i2c)
dht_device = adafruit_dht.DHT22(board.D4)

while True:
    try:
        temperature = dht_device.temperature
        humidity = dht_device.humidity
        uv_index = ltr.lux
        ambient_light = ltr.light
        print(f"Temp: {temperature:.1f}°C, Hum: {humidity:.1f}%, UV: {uv_index:.1f}, Ambient Light: {ambient_light:.1f}")
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(2)