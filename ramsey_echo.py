# -*- coding: utf-8 -*-
import os
import time

import h5py
import numpy as np

from mla_server import set_dc_bias
from presto.hardware import AdcFSample, AdcMode, DacFSample, DacMode
from presto import pulsed
from presto.utils import get_sourcecode, sin2

# import load_ramsey_echo

WHICH_QUBIT = 2  # 1 (higher resonator) or 2 (lower resonator)
USE_JPA = True
WITH_COUPLER = False

# Presto's IP address or hostname
ADDRESS = "130.237.35.90"
PORT = 42874
EXT_REF_CLK = False  # set to True to lock to an external reference clock
jpa_bias_port = 1

if WHICH_QUBIT == 1:
    if WITH_COUPLER:
        readout_freq = 6.167_009 * 1e9  # Hz, frequency for resonator readout
        control_amp_90 = 0.267  # FS <-- pi/2 pulse
        control_freq = 3.556_520 * 1e9  # Hz
    else:
        readout_freq = 6.166_600 * 1e9  # Hz, frequency for resonator readout
        control_amp_90 = 0.05129  # FS <-- pi/2 pulse
        control_freq = 3.557_866 * 1e9  # Hz
    control_port = 3
    jpa_pump_freq = 2 * 6.169e9  # Hz
    jpa_pump_pwr = 11  # lmx units
    jpa_bias = +0.437  # V
elif WHICH_QUBIT == 2:
    if WITH_COUPLER:
        readout_freq = 6.029_130 * 1e9  # Hz, frequency for resonator readout
        control_amp_90 = 0.380  # FS <-- pi/2 pulse
        control_freq = 4.093_042 * 1e9  # Hz
    else:
        readout_freq = 6.028_450 * 1e9  # Hz, frequency for resonator readout
        control_amp_90 = 0.3808  # FS <-- pi/2 pulse
        control_amp_180 = 0.7617  # FS <-- pi pulse
        control_freq = 4.093_372 * 1e9  # Hz
    control_port = 4
    jpa_pump_freq = 2 * 6.031e9  # Hz
    jpa_pump_pwr = 9  # lmx units
    jpa_bias = +0.449  # V
else:
    raise ValueError

# cavity drive: readout
readout_amp = 0.1  # FS
readout_duration = 2e-6  # s, duration of the readout pulse
readout_port = 1

# qubit drive: control
control_if = 0 * 1e6  # Hz
control_duration = 20 * 1e-9  # s, duration of the control pulse

# cavity readout: sample
sample_duration = 4 * 1e-6  # s, duration of the sampling window
sample_port = 1

# Ramsey experiment
# num_averages = 1_000
num_averages = 10_000
# nr_delays = 128  # number of steps when changing delay between control and readout pulses
nr_delays = 256  # number of steps when changing delay between control and readout pulses
# dt_delays = 0.1 * 1e-6  # s, step size when changing delay between control and readout pulses
dt_delays = 0.4 * 1e-6  # s, step size when changing delay between control and readout pulses
wait_delay = 200e-6  # s, delay between repetitions to allow the qubit to decay
readout_sample_delay = 290 * 1e-9  # s, delay between readout pulse and sample window to account for latency

# Instantiate interface class
with pulsed.Pulsed(
        address=ADDRESS,
        port=PORT,
        ext_ref_clk=EXT_REF_CLK,
        adc_mode=AdcMode.Mixed,
        adc_fsample=AdcFSample.G2,
        dac_mode=[DacMode.Mixed42, DacMode.Mixed02, DacMode.Mixed02, DacMode.Mixed02],
        dac_fsample=[DacFSample.G10, DacFSample.G6, DacFSample.G6, DacFSample.G6],
) as pls:
    pls.hardware.set_adc_attenuation(sample_port, 0.0)
    pls.hardware.set_dac_current(readout_port, 32_000)
    pls.hardware.set_dac_current(control_port, 32_000)
    pls.hardware.set_inv_sinc(readout_port, 0)
    pls.hardware.set_inv_sinc(control_port, 0)
    pls.hardware.configure_mixer(
        freq=readout_freq,
        in_ports=sample_port,
        out_ports=readout_port,
        sync=False,  # sync in next call
    )
    pls.hardware.configure_mixer(
        freq=control_freq - control_if,
        out_ports=control_port,
        sync=True,  # sync here
    )
    if USE_JPA:
        pls.hardware.set_lmx(jpa_pump_freq, jpa_pump_pwr)
        set_dc_bias(jpa_bias_port, jpa_bias)
        time.sleep(1.0)

    # ************************************
    # *** Setup measurement parameters ***
    # ************************************

    # Setup lookup tables for frequencies
    # we only need to use carrier 1
    pls.setup_freq_lut(
        output_ports=readout_port,
        group=0,
        frequencies=0.0,
        phases=0.0,
        phases_q=0.0,
    )
    pls.setup_freq_lut(
        output_ports=control_port,
        group=0,
        frequencies=control_if,
        phases=0.0,
        phases_q=0.0 if control_if == 0.0 else -np.pi / 2,
    )

    # Setup lookup tables for amplitudes
    pls.setup_scale_lut(
        output_ports=readout_port,
        group=0,
        scales=readout_amp,
    )
    pls.setup_scale_lut(
        output_ports=control_port,
        group=0,
        # scales=control_amp,
        scales=1.0,
    )

    # Setup readout and control pulses
    # use setup_long_drive to create a pulse with square envelope
    # setup_long_drive supports smooth rise and fall transitions for the pulse,
    # but we keep it simple here
    readout_pulse = pls.setup_long_drive(
        output_port=readout_port,
        group=0,
        duration=readout_duration,
        amplitude=1.0,
        amplitude_q=1.0,
        rise_time=0e-9,
        fall_time=0e-9,
    )
    control_ns = int(round(control_duration * pls.get_fs("dac")))  # number of samples in the control template
    control_envelope = sin2(control_ns)
    control_pulse_90 = pls.setup_template(
        output_port=control_port,
        group=0,
        template=control_amp_90 * control_envelope,
        template_q=control_amp_90 * control_envelope,
        envelope=True,
    )
    control_pulse_180 = pls.setup_template(
        output_port=control_port,
        group=0,
        template=control_amp_180 * control_envelope,
        template_q=control_amp_180 * control_envelope,
        envelope=True,
    )

    # Setup sampling window
    pls.set_store_ports(sample_port)
    pls.set_store_duration(sample_duration)

    # ******************************
    # *** Program pulse sequence ***
    # ******************************
    T = 0.0  # s, start at time zero ...
    for ii in range(nr_delays):
        pls.reset_phase(T, control_port)
        # first pi/2 pulse
        pls.output_pulse(T, control_pulse_90)
        T += control_duration
        # wait first half
        T += ii * dt_delays / 2
        # pi pulse, echo
        pls.output_pulse(T, control_pulse_180)
        T += control_duration
        # wait second half
        T += ii * dt_delays / 2
        # second pi/2 pulse
        pls.output_pulse(T, control_pulse_90)
        T += control_duration
        # Readout pulse starts after control pulse,
        # with an increasing delay
        pls.reset_phase(T, readout_port)
        pls.output_pulse(T, readout_pulse)
        # Sampling window
        pls.store(T + readout_sample_delay)
        # Move to next iteration
        T += readout_duration
        T += wait_delay

    # **************************
    # *** Run the experiment ***
    # **************************
    pls.run(
        period=T,
        repeat_count=1,
        num_averages=num_averages,
        print_time=True,
    )
    t_arr, (data_I, data_Q) = pls.get_store_data()
    if USE_JPA:
        pls.hardware.set_lmx(0.0, 0.0)
        set_dc_bias(jpa_bias_port, 0.0)

store_arr = data_I + 1j * data_Q

# *************************
# *** Save data to HDF5 ***
# *************************
script_path = os.path.realpath(__file__)  # full path of current script
current_dir, script_basename = os.path.split(script_path)
script_filename = os.path.splitext(script_basename)[0]  # name of current script
timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())  # current date and time
save_basename = f"{script_filename:s}_{timestamp:s}.h5"  # name of save file
save_path = os.path.join(current_dir, "data", save_basename)  # full path of save file
source_code = get_sourcecode(__file__)  # save also the sourcecode of the script for future reference
with h5py.File(save_path, "w") as h5f:
    dt = h5py.string_dtype(encoding='utf-8')
    ds = h5f.create_dataset("source_code", (len(source_code), ), dt)
    for ii, line in enumerate(source_code):
        ds[ii] = line
    h5f.attrs["num_averages"] = num_averages
    h5f.attrs["control_freq"] = control_freq
    h5f.attrs["control_if"] = control_if
    h5f.attrs["readout_freq"] = readout_freq
    h5f.attrs["readout_duration"] = readout_duration
    h5f.attrs["control_duration"] = control_duration
    h5f.attrs["readout_amp"] = readout_amp
    h5f.attrs["control_amp_90"] = control_amp_90
    h5f.attrs["control_amp_180"] = control_amp_180
    h5f.attrs["sample_duration"] = sample_duration
    h5f.attrs["nr_delays"] = nr_delays
    h5f.attrs["dt_delays"] = dt_delays
    h5f.attrs["wait_delay"] = wait_delay
    h5f.attrs["readout_sample_delay"] = readout_sample_delay
    h5f.create_dataset("t_arr", data=t_arr)
    h5f.create_dataset("store_arr", data=store_arr)
print(f"Data saved to: {save_path}")

# *****************
# *** Plot data ***
# *****************
# load_ramsey_echo.load(save_path)
