def run():
    print("Starting diagnostic mode...")

    test_system()
    test_leds()
    test_bme280()
    test_lora()
    test_sd_card()

    print("Diagnostic complete")

    while True:
        time.sleep(1)