## Basic functionality HWIL test

The preferred basic compatibility check is the supervised HWIL runner:

```shell
uv run anechoic-turntable-hwil
```

Use `--port /dev/...` to bypass serial-port discovery or `--report PATH` to
select the JSON result path. This command operates physical motors. Run it only
while present at the table, with its entire travel area clear and the emergency
power disconnect immediately accessible. A second person ready to disconnect
power is strongly recommended.

The runner checks communication and firmware-version reporting before allowing
motion. It then repeats this centering procedure until the operator confirms
physical zero:

1. Enter the best available estimate of the current physical pan and tilt.
2. Review the signs, target, estimated travel duration, and hard timeout.
3. Explicitly approve SET of that estimate and the move to pan `+0`, tilt `+0`.
4. Confirm that the motion appeared correct and safe.
5. Confirm whether the resulting physical position is actually centered.
6. If it is not centered, enter the remaining observed offset and repeat.

The estimate is safety-critical: it determines the direction and distance of
the following move. Do not guess when the physical orientation, coordinate
signs, or clear travel path are uncertain.

Once centered, the runner moves to pan `+5`, tilt `+0`; returns home; moves to pan
`+0`, tilt `+5`; and returns home again. It asks for approval before every move
and physical confirmation afterward. Any negative result ends the test. Ctrl-C
at any point requests an immediate stop. The runner also attempts a final stop
on success, cancellation, or failure and writes a JSON report containing the
observed trace and results.

Positions and movement amounts displayed for operator confirmation are rounded
to the nearest degree. Exact command bytes remain visible in the subdued serial
trace, whose position lines update at about 3 Hz with three decimal places.
Movement position lines show both the current coordinates and the remaining
signed pan/tilt delta to the target. All operator-facing angles include an
explicit `+` or `-` sign.

## Quick Test Procedure
Run through these commands before actually testing changes you made:

1. Make sure that the turntable is relatively in the "0,0" or "home" position. Then set the position using the set button.
2. Move the turntable to pan = 5, tilt = 5. You can do this using the TUI. Then move back to "home" position.
3. Test the emergency stop button.
	1. Queue the turntable to move to pan = 90. Then after 5 seconds, hit the emergency stop button. Then move back to "home".
	2. Queue the turntable to move to tilt = -80. After 5 seconds, hit the emergency stop. Then move back to "home"

**Optional steps**
1. Allow the turntable to successfully complete a "large" move.
	1. Move the turntable to pan = 90. Then go back to home.
	2. Move the turntable to tilt = -80. Then go back home.
2. You can also do a combination of pan and tilt "large" moves if you want to test that they work at the same time.

## Build Your Test Firmware

On your branch, make any of the changes to the code that you want to test. Make sure to properly label your build test, especially if it could potentially be something dangerous (i.e. something that causes the turntable to stop listening to commands).

The steps for building your code can be found in `firmware-build.md`
Then you can program the STM32 with your `.elf` file.

## Programming the Controller With A Build

To actually flash firmware onto the STM32, follow these steps:

1. Make sure you have built the firmware, either with a working release, or with a build you want to test.
2. This should be an `.elf` file, located in `firmware/Debug`.
3. Connect your computer to the STM32 with the USB.
4. Open the STM32Cube Programmer software.
5. Make sure the blue button on the top right, next to connect, is set to "ST-LINK"
6. In the right pane of the software, click the "refresh" button (should look like two arrows making a circle.)
7. Make sure the settings in the right pane are:
	- Serial Number: Should just be the serial number to the ST Link.
	- Port: SWD
	- Frequency:
	- Mode: Under reset
	- Access Port: 0
	- Reset mode: Hardware reset
	- Speed: Reliable
	- Shared: Disabled
8. Hit the green "Connect" button on the top right. Now you are connected to the ST-Link.
9. Navigate to the left side of the screen, and click the "Erasing and Programming" button. (Should look like an arrow pointing down into a rectangle)
10. Browse to your `.elf` file. Then click open.
11. Make sure "Run after programming" is CHECKED and everything else is NOT CHECKED.
12. Then hit "Start Programming"
Now your build is programmed onto the STM32! Make sure to hit "disconnect" after flashing successfully!


## For Testing New Features

When you test a new feature, you want to go in this order:

1. First run through the "quick test procedure" using a working version of the firmware/controller. Releases can be found on the GitHub.
2. After testing with a known working version, make a build using the code with the changes you want to test. Make sure to properly label your test build elf file, especially if something could go wrong during testing.
3. With your test build, run through the quick test procedure. Make sure everything is working normally.
	1. If you have to change things in your firmware to test/debug, be sure to label those areas so you don't forget to change them later!
4. Run through any other tests regarding the changes you make. Be safe, and make sure you are able to emergency stop or unplug the power if needed!
5. After testing the test build, make sure everything is disconnected or unplugged.
6. If you changed anything in the firmware to test/debug, revert those changes to the correct values.
	1. Build again with the "correct test" firmware
	2. Run through quick test procedures, and any other tests you want to see.
7. If everything is working, you can make a pull request and merge your changes! Then make sure to build the correct and latest firmware back onto the board.
	1. If something is NOT working, do not merge it onto main. Make sure you build the latest and working firmware back on the board, without your changes.


## Other Tips

1. It's good to have two people while running tests. One can run the software, while another can be in the anechoic chamber ready to unplug the turntable if something goes wrong.
2. Instead of testing multiple things, test one feature at a time. It's also good to make separate branches for features.
3. Make sure everything is plugged in correctly, and you know which build is on the STM32 at all times.
4. Have fun! :)
