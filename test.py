import time
import board
import busio
import adafruit_ltr390
import adafruit_dht

# Inicializar I2C para el LTR390
i2c = busio.I2C(board.SCL, board.SDA)
ltr = adafruit_ltr390.LTR390(i2c)

# Inicializar DHT22 en GPIO14
dht = adafruit_dht.DHT22(board.D14)

# Bucle principal
while True:
    try:
        # Leer datos del LTR390
        uv_index = ltr.lux
        ambient_light = ltr.light

        # Leer datos del DHT22
        temperature_c = dht.temperature
        humidity = dht.humidity

        # Mostrar los datos
        print(f"--- Medición ---")
        print(f"Luz ambiente (lux): {ambient_light}")
        print(f"Índice UV: {uv_index}")
        print(f"Temperatura: {temperature_c:.1f} °C")
        print(f"Humedad: {humidity:.1f} %")
        print("-----------------\n")

    except Exception as e:
        print(f"Error al leer sensores: {e}")

    # Esperar 2 segundos antes de la próxima lectura
    time.sleep(2)