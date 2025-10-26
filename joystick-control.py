import carla
import pygame
import time
import os
import sys
import datetime

def main():
    # Initialize pygame and joystick
    pygame.init()
    #pygame.joystick.init()
    # Setup logging to file (tee stdout/stderr)
    log_file = None
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr
    try:
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base_dir = os.getcwd()
        log_path = os.path.join(base_dir, 'joystick-log.txt')
        # open in append mode
        log_file = open(log_path, 'a', buffering=1, encoding='utf-8', errors='replace')

        class Tee:
            def __init__(self, a, b):
                self.a = a
                self.b = b
            def write(self, s):
                try:
                    self.a.write(s)
                except Exception:
                    pass
                try:
                    self.b.write(s)
                except Exception:
                    pass
            def flush(self):
                try:
                    self.a.flush()
                except Exception:
                    pass
                try:
                    self.b.flush()
                except Exception:
                    pass

        sys.stdout = Tee(_orig_stdout, log_file)
        sys.stderr = Tee(_orig_stderr, log_file)
        print(f"\n--- LOG START {datetime.datetime.now().isoformat()} ---")
    except Exception:
        # if logging setup fails, continue without file logging
        try:
            if log_file:
                log_file.close()
        except Exception:
            pass
    
    joystick = None
    if pygame.joystick.get_count() > 0:
        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        print(f"Joystick detected: {joystick.get_name()}")
        print(f"axes={joystick.get_numaxes()} buttons={joystick.get_numbuttons()} hats={joystick.get_numhats()}")

    # Auto-detect clutch as the last axis (commonly a slider)
    throttle_axis = 2
    brake_axis = 5
    clutch_axis = joystick.get_numaxes() - 1 if joystick and joystick.get_numaxes() > 0 else None
    print(f"Auto-mapped clutch to axis {clutch_axis} (slider)")

    print(f"Final mapping: throttle={throttle_axis} brake={brake_axis} clutch={clutch_axis}")

    # connect CARLA
    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    blueprint_library = world.get_blueprint_library()
    bp = blueprint_library.filter('vehicle.tesla.model3')[0]
    spawn_point = world.get_map().get_spawn_points()[0]
    vehicle = world.spawn_actor(bp, spawn_point)
    actor_list = [vehicle]
    current_gear = 1
    prev_gear = current_gear


    # buttons
    reverse_button = 5
    hand_brake_button = 4
    hand_brake_hold = False
    hand_brake = False
    # persistent reverse mode (toggle)
    reverse_mode = False
    reverse_pending = False
    debug_button = 1
    debug = False
    detect_button = 2
    detect = False
    # If True, pressing the throttle will automatically cancel reverse. Default False
    throttle_exit_reverse = False

    prev_axes = [0.0] * (joystick.get_numaxes() if joystick else 0)
    prev_buttons_full = [0] * (joystick.get_numbuttons() if joystick else 0)
    try:
        prev_hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())] if joystick else []
    except Exception:
        prev_hats = []

    pedal_debug = True
    pedal_debug_threshold = 0.05
    prev_raw_throttle = None
    prev_raw_brake = None
    prev_raw_clutch = None

    # Per-axis inversion flags: flip mapping for axes that report opposite polarity
    invert_throttle = False
    invert_brake = False
    invert_clutch = False

    def _normalize_pedal(raw, invert=False):
        """Map raw axis value in [-1,1] to normalized [0,1].
        If invert=True the result is flipped (1 -> 0, 0 -> 1).
        This is a simple, robust mapping that avoids the previous heuristic which
        could produce near-zero values for common pedal positions.
        """
        try:
            # clamp raw to [-1,1]
            if raw is None:
                return 0.0
            r = max(-1.0, min(1.0, float(raw)))
            val = (r + 1.0) / 2.0
            return 1.0 - val if invert else val
        except Exception:
            return 0.0
        

    try:
        while True:
            pygame.event.pump()

            steer = joystick.get_axis(0) if joystick and joystick.get_numaxes() > 0 else 0.0

            # read pedals
            raw_throttle = joystick.get_axis(throttle_axis) if joystick and joystick.get_numaxes() > throttle_axis else -1.0
            raw_brake = joystick.get_axis(brake_axis) if joystick and brake_axis is not None and joystick.get_numaxes() > brake_axis else -1.0
            # Always normalize without inverting here; apply inversion later based on reverse state so toggle takes effect immediately
            throttle_norm = _normalize_pedal(raw_throttle, invert=False)
            throttle = throttle_norm
            brake = _normalize_pedal(raw_brake, invert=invert_brake)

            # pedal debug
            if pedal_debug:
                try:
                    if prev_raw_throttle is None or abs(raw_throttle - prev_raw_throttle) > pedal_debug_threshold:
                        print(f"pedal detected: throttle axis {throttle_axis} raw {raw_throttle:.3f} -> norm {throttle:.3f}")
                        prev_raw_throttle = raw_throttle
                    if prev_raw_brake is None or abs(raw_brake - prev_raw_brake) > pedal_debug_threshold:
                        print(f"pedal detected: brake axis {brake_axis} raw {raw_brake:.3f} -> norm {brake:.3f}")
                        prev_raw_brake = raw_brake
                except Exception:
                    pass

            # read buttons
            num_buttons = joystick.get_numbuttons() if joystick else 0
            buttons = [joystick.get_button(i) for i in range(num_buttons)] if joystick else []

            # clutch
            try:
                raw_clutch = joystick.get_axis(clutch_axis) if joystick and clutch_axis is not None and clutch_axis < joystick.get_numaxes() else -1.0
                clutch = _normalize_pedal(raw_clutch, invert=invert_clutch)
            except Exception:
                clutch = 0.0

            if pedal_debug:
                try:
                    if prev_raw_clutch is None or abs(raw_clutch - prev_raw_clutch) > pedal_debug_threshold:
                        print(f"pedal detected: clutch axis {clutch_axis} raw {raw_clutch:.3f} -> norm {clutch:.3f}")
                        prev_raw_clutch = raw_clutch
                except Exception:
                    pass

            # Event-based reverse toggle: handle JOYBUTTONDOWN from any device
            for ev in pygame.event.get():
                if ev.type == pygame.JOYBUTTONDOWN:
                    print(f"EVENT: JOYBUTTONDOWN device={getattr(ev, 'instance_id', '?')} button={ev.button}")
                    try:
                        if ev.button == reverse_button:
                            # Toggle behavior: request reverse if currently not in reverse; otherwise turn it off
                            if not reverse_mode and not reverse_pending:
                                print("debug: reverse requested -> will brake until stop then engage")
                                reverse_pending = True
                            else:
                                reverse_mode = False
                                reverse_pending = False
                                print("debug: reverse toggled off")
                        # keep legacy toggles (handbrake/debug/detect) available via buttons as well
                        elif ev.button == hand_brake_button:
                            if hand_brake_hold:
                                hand_brake = bool(buttons[hand_brake_button])
                            else:
                                hand_brake = not hand_brake
                                print(f"debug: hand_brake toggled -> {hand_brake}")
                        elif ev.button == debug_button:
                            debug = not debug
                        elif ev.button == detect_button:
                            detect = not detect
                    except Exception:
                        pass

            # compute current speed
            try:
                vel = vehicle.get_velocity()
                speed = (vel.x ** 2 + vel.y ** 2 + vel.z ** 2) ** 0.5
            except Exception:
                speed = 0.0

            # If reverse was requested, brake the vehicle until it's (nearly) stopped, then engage reverse
            if reverse_pending:
                # apply an aggressive brake request to encourage stopping
                if speed > 0.5:
                    print(f"debug: reverse pending, braking (speed={speed:.3f})")
                    brake = max(brake, 1.0)
                    throttle = 0.0
                else:
                    reverse_mode = True
                    reverse_pending = False
                    print("debug: reverse engaged after stopping")

            # keep throttle inversion in sync with reverse state
            invert_throttle = bool(reverse_mode)

            # apply inversion to the already-normalized throttle value
            try:
                throttle = 1.0 - throttle_norm if invert_throttle else throttle_norm
            except Exception:
                throttle = throttle_norm

            # set logical current_gear for diagnostics (automatic transmission is used)
            current_gear = -1 if reverse_mode else 1
            # If configured, pressing throttle can cancel reverse (optional; disabled by default)
            if throttle_exit_reverse and reverse_mode and throttle > 0.1:
                reverse_mode = False
                print("debug: throttle exited reverse (throttle_exit_reverse enabled)")

            # gear changed
            try:
                if current_gear != prev_gear:
                    print(f"gear changed -> {current_gear}")
                    prev_gear = current_gear
            except Exception:
                pass

            # apply control
            control = carla.VehicleControl()
            control.steer = steer
            control.throttle = throttle
            control.brake = brake
            control.hand_brake = hand_brake
            # Use automatic transmission so throttle/brake control is enough.
            # This disables manual gearbox forcing inside CARLA and lets reverse
            # be applied via the reverse flag/gear value.
            control.manual_gear_shift = False
            # Some control schemes expect the gear sign to indicate direction
            # (negative gear -> reverse). Set gear signed when reverse is active
            # and also keep the reverse flag in sync for compatibility.
            try:
                g = int(current_gear)
            except Exception:
                g = 1
            if g == 0:
                g = 1
            if current_gear < 0:
                control.gear = -abs(g)
                control.reverse = True
            else:
                control.gear = abs(g)
                control.reverse = False
            # Experimental debug: if debug mode is enabled and reverse is active,
            # force a small throttle and disable manual_gear_shift so we can test
            # whether CARLA will move the vehicle backwards when reverse=True.
            # Toggle debug with the configured debug button in-game.
            if debug and control.reverse:
                try:
                    print("DEBUG-FORCE: applying experimental reverse throttle (manual_gear_shift->False, throttle=0.25)")
                    control.manual_gear_shift = False
                    control.throttle = max(control.throttle, 0.25)
                    # ensure gear is set to a sane positive value while using reverse flag
                    control.gear = 1
                except Exception:
                    pass

            # Debug: print control being sent to CARLA and current vehicle velocity
            try:
                print(f"CONTROL-> reverse={control.reverse} gear={control.gear} throttle={control.throttle:.3f} brake={control.brake:.3f} manual_shift={control.manual_gear_shift}")
                v = vehicle.get_velocity()
                speed = (v.x ** 2 + v.y ** 2 + v.z ** 2) ** 0.5
                print(f"VEHICLE-> speed={speed:.3f} vel=({v.x:.3f},{v.y:.3f},{v.z:.3f})")
            except Exception:
                pass

            vehicle.apply_control(control)

            # handbrake & toggles
            try:
                if hand_brake_button is not None and hand_brake_button < len(buttons):
                    if hand_brake_hold:
                        hand_brake = bool(buttons[hand_brake_button])
                    else:
                        # rising-edge toggle for handbrake on button 4
                        if hand_brake_button < len(prev_buttons) and buttons[hand_brake_button] and not prev_buttons[hand_brake_button]:
                            hand_brake = not hand_brake
                            print(f"debug: hand_brake toggled -> {hand_brake}")
            except Exception:
                pass

            # spectator follow
            spectator = world.get_spectator()
            vehicle_transform = vehicle.get_transform()
            v_loc = vehicle_transform.location
            v_rot = vehicle_transform.rotation
            behind_distance = 8.0
            height_offset = 3.0
            import math
            yaw_rad = math.radians(v_rot.yaw)
            dx = -behind_distance * math.cos(yaw_rad)
            dy = -behind_distance * math.sin(yaw_rad)
            spec_loc = carla.Location(x=v_loc.x + dx, y=v_loc.y + dy, z=v_loc.z + height_offset)
            look_at = v_loc
            direction = look_at - spec_loc
            dist_xy = math.sqrt(direction.x * direction.x + direction.y * direction.y)
            pitch = -math.degrees(math.atan2(direction.z, dist_xy))
            yaw = math.degrees(math.atan2(direction.y, direction.x))
            spec_rot = carla.Rotation(pitch=pitch, yaw=yaw, roll=0.0)
            spec_transform = carla.Transform(spec_loc, spec_rot)
            try:
                cur = spectator.get_transform()
                lerp = 0.2
                new_loc = carla.Location(x=cur.location.x + (spec_transform.location.x - cur.location.x) * lerp,
                                         y=cur.location.y + (spec_transform.location.y - cur.location.y) * lerp,
                                         z=cur.location.z + (spec_transform.location.z - cur.location.z) * lerp)
                new_rot = carla.Rotation(pitch=cur.rotation.pitch + (spec_transform.rotation.pitch - cur.rotation.pitch) * lerp,
                                         yaw=cur.rotation.yaw + (spec_transform.rotation.yaw - cur.rotation.yaw) * lerp,
                                         roll=cur.rotation.roll + (spec_transform.rotation.roll - cur.rotation.roll) * lerp)
                spectator.set_transform(carla.Transform(new_loc, new_rot))
            except Exception:
                spectator.set_transform(spec_transform)

            # tick
            world.tick()

            # debug prints
            if debug:
                try:
                    print(f"steer={steer:.3f} throttle={throttle:.3f} brake={brake:.3f} clutch={clutch:.3f} gear={current_gear} hand_brake={hand_brake}")
                    print(f"axes={[round(joystick.get_axis(i),3) for i in range(joystick.get_numaxes())]}")
                    print(f"buttons={[joystick.get_button(i) for i in range(joystick.get_numbuttons())]}")
                except Exception:
                    pass

            # detect mode
            if detect:
                try:
                    for i in range(joystick.get_numaxes()):
                        a = joystick.get_axis(i)
                        if i >= len(prev_axes) or abs(a - prev_axes[i]) > 0.01:
                            print(f"axis[{i}] changed -> {a:.3f}")
                    for i in range(joystick.get_numbuttons()):
                        b = joystick.get_button(i)
                        if i >= len(prev_buttons_full) or b != prev_buttons_full[i]:
                            print(f"button[{i}] changed -> {b}")
                    for i in range(joystick.get_numhats()):
                        h = joystick.get_hat(i)
                        if i >= len(prev_hats) or h != prev_hats[i]:
                            print(f"hat[{i}] changed -> {h}")
                    prev_axes = [joystick.get_axis(i) for i in range(joystick.get_numaxes())]
                    prev_buttons_full = [joystick.get_button(i) for i in range(joystick.get_numbuttons())]
                    prev_hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]
                except Exception:
                    pass
    except KeyboardInterrupt:
        print("Exiting simulation...")
    finally:
        try:
            print(f"--- LOG END {datetime.datetime.now().isoformat()} ---\n")
        except Exception:
            pass
        print("Destroying actors")
        for actor in actor_list:
            try:
                actor.destroy()
            except Exception:
                pass
        pygame.quit()
        # restore stdout/stderr and close log file if we replaced them
        try:
            sys.stdout = _orig_stdout
            sys.stderr = _orig_stderr
        except Exception:
            pass
        try:
            if log_file:
                log_file.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
