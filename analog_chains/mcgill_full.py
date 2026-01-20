import numpy as np
import os
import pickle

import hidfmux.core.utils.user_config as config

from hidfmux.core.resources.analog_chain import AnalogChain
import hidfmux.core.resources.hardware_models as hardware_models
import hidfmux.core.utils.transferfunctions as transferfunctions
from hidfmux.core.utils.transferfunctions import to_dbm, to_W



class McGillFull_meas(AnalogChain):
    
    def __init__(self):
        

        self.ad9082 = hardware_models.AD9082()
        
        # measured mcgill cryostat inputline attenuation:
        self.cs_input_gain = transferfunctions.load_transferfunction(os.path.join(config.get_tf_parent_dir(), 'mcgill_DRonly_input.pkl'))
        
        # input cables
        self.warm_cables_in = hardware_models.SMA_cables(length_m=3)

        # extra input attenuator
        self.atten300K_input = hardware_models.Attenuator(-9, 300)
        
        # return amplifiers etc
        self.lna = hardware_models.CryoElec_LNA()
        self.wa1 = hardware_models.ZX60_3018Gplus()
        self.wa2 = hardware_models.ZX60_3018Gplus()
        self.warm_cables_return = hardware_models.SMA_cables(length_m=3)
        self.cryo_cables_return = hardware_models.SMA_CuNi_cryo(length_m=1.5, temperature=4)
        self.atten300K_return = hardware_models.Attenuator(-9, 300)

        # measured mcgill cryostat outputline gain
        self.cs_output_gain = transferfunctions.load_transferfunction(os.path.join(config.get_tf_parent_dir(), 'mcgill_DRonly_return_wLNA.pkl'))
        
        
        
    def input_gain(self, carrier_freq):
        
        return self.cs_input_gain(carrier_freq) + self.warm_cables_in.gain(carrier_freq) + self.atten300K_input.gain_meas(carrier_freq)
    
    
    def return_gain(self, carrier_freq, carrier_power_dbm=None, return_carrier_power_dbm=None):

        if return_carrier_power_dbm is not None and carrier_power_dbm is not None:
            # legacy call
            return_gain = compute_return_gain(carrier_freq, carrier_power_dbm, return_carrier_power_dbm)
            return return_gain
        
        return_gain = self.cs_output_gain(carrier_freq) + self.wa1.gain(carrier_freq) + self.wa2.gain(carrier_freq) + self.warm_cables_return.gain(carrier_freq) + self.atten300K_return.gain_meas(carrier_freq)
        return return_gain

    def compute_return_gain(self, carrier_freq, carrier_power_dbm, return_carrier_power_dbm):

        return_gain = return_carrier_power_dbm - self.input_gain(carrier_freq) - carrier_power_dbm

        return return_gain
    
    
    def output_noise(self, carrier_freq, spectral_freq, carrier_power_dbm, return_carrier_power_dbm=None):

        if return_carrier_power_dbm is None:
            return_gain = self.return_gain(carrier_freq)
        else:
            return_gain = self.compute_return_gain(carrier_freq, carrier_power_dbm, return_carrier_power_dbm)
        
        n_dac = self.ad9082.dac_noise(spectral_freq, carrier_power_dbm)
        n_dac_output = to_dbm(n_dac) + self.input_gain(carrier_freq) + return_gain #self.return_gain(carrier_freq, carrier_power_dbm, return_carrier_power_dbm)
        
        # noise of other analog components is small compared to noise of LNA
        n_lna = to_dbm(self.lna.noise(carrier_freq)) + return_gain# self.return_gain(carrier_freq, carrier_power_dbm, return_carrier_power_dbm)

        # totals at output
        noise_total = to_W(n_dac_output) + to_W(n_lna)
        
        return noise_total
    
    
class McGillFull_meas_TiN(AnalogChain):
    
    def __init__(self):
        

        self.ad9082 = hardware_models.AD9082()
        
        # measured mcgill cryostat inputline attenuation:
        self.cs_input_gain = transferfunctions.load_transferfunction(os.path.join(config.get_tf_parent_dir(), 'mcgill_DRonly_input.pkl'))
        
        # input cables
        self.warm_cables_in = hardware_models.SMA_cables(length_m=3)

        # extra input attenuator
        self.atten300K_input = hardware_models.Attenuator(-26, 300)
        
        # return amplifiers etc
        self.lna = hardware_models.CryoElec_LNA()
        self.wa1 = hardware_models.ZX60_3018Gplus()
        self.wa2 = hardware_models.ZX60_3018Gplus()
        self.warm_cables_return = hardware_models.SMA_cables(length_m=3)
        self.cryo_cables_return = hardware_models.SMA_CuNi_cryo(length_m=1.5, temperature=4)
        self.atten300K_return = hardware_models.Attenuator(-9, 300)

        # measured mcgill cryostat outputline gain
        self.cs_output_gain = transferfunctions.load_transferfunction(os.path.join(config.get_tf_parent_dir(), 'mcgill_DRonly_return_wLNA.pkl'))
        
        
        
    def input_gain(self, carrier_freq):
        
        return self.cs_input_gain(carrier_freq) + self.warm_cables_in.gain(carrier_freq) + self.atten300K_input.gain_meas(carrier_freq)
    
    
    def return_gain(self, carrier_freq, carrier_power_dbm=None, return_carrier_power_dbm=None):

        if return_carrier_power_dbm is not None or carrier_power_dbm is not None:
            # legacy call
            return_gain = compute_return_gain(carrier_freq, carrier_power_dbm, return_carrier_power_dbm)
            return return_gain
        
        return_gain = self.cs_output_gain(carrier_freq) + self.wa1.gain(carrier_freq) + self.wa2.gain(carrier_freq) + self.warm_cables_return.gain(carrier_freq) + self.atten300K_return.gain_meas(carrier_freq)
        return return_gain

    def compute_return_gain(self, carrier_freq, carrier_power_dbm, return_carrier_power_dbm):

        return_gain = return_carrier_power_dbm - self.input_gain(carrier_freq) - carrier_power_dbm

        return return_gain
    
    
    def output_noise(self, carrier_freq, spectral_freq, carrier_power_dbm, return_carrier_power_dbm=None):

        if return_carrier_power_dbm is None:
            return_gain = self.return_gain(carrier_freq)
        else:
            return_gain = self.compute_return_gain(carrier_freq, carrier_power_dbm, return_carrier_power_dbm)
        
        n_dac = self.ad9082.dac_noise(spectral_freq, carrier_power_dbm)
        n_dac_output = to_dbm(n_dac) + self.input_gain(carrier_freq) + return_gain #self.return_gain(carrier_freq, carrier_power_dbm, return_carrier_power_dbm)
        
        # noise of other analog components is small compared to noise of LNA
        n_lna = to_dbm(self.lna.noise(carrier_freq)) + return_gain# self.return_gain(carrier_freq, carrier_power_dbm, return_carrier_power_dbm)

        # totals at output
        noise_total = to_W(n_dac_output) + to_W(n_lna)
        
        return noise_total    
    


class McGillFull_modeled(AnalogChain):
    
    def __init__(self):

        self.ad9082 = hardware_models.AD9082()
        
        # input attenuation
        self.atten_300K = hardware_models.Attenuator(-9, 300)
        self.atten_4K = hardware_models.Attenuator(-20, 4)
        self.atten_still = hardware_models.Attenuator(0, 0.7)
        self.atten_mxc = hardware_models.Attenuator(-20, 0.03) ###
        
        # input cables
        self.warm_cables_in = hardware_models.SMA_cables(length_m=3)
        self.cryo_cables_in = hardware_models.SMA_CuNi_cryo(length_m=1.5, temperature=4)
        
        # return amplifiers etc
        self.lna = hardware_models.CryoElec_LNA()
        self.wa1 = hardware_models.ZX60_3018Gplus()
        self.wa2 = hardware_models.ZX60_3018Gplus()
        self.warm_cables_return = hardware_models.SMA_cables(length_m=3)
        self.cryo_cables_return = hardware_models.SMA_CuNi_cryo(length_m=1.5, temperature=4)
        self.atten_return_warm = hardware_models.Attenuator(-9, 300)
        
        
    def input_gain(self, carrier_freq):
        
        atten_input_gain = self.atten_300K.gain_meas(carrier_freq) + self.atten_4K.gain_meas(carrier_freq) + self.atten_still.gain_meas(carrier_freq) + self.atten_mxc.gain_meas(carrier_freq)
        cable_input_gain = self.warm_cables_in.gain(carrier_freq) + self.cryo_cables_in.gain(carrier_freq)
        
        return atten_input_gain + cable_input_gain
    
    
    def return_gain(self, carrier_freq):
        
        return_gain = self.lna.gain(carrier_freq) + self.wa1.gain(carrier_freq) + self.wa2.gain(carrier_freq) + self.cryo_cables_return.gain(carrier_freq) + self.warm_cables_return.gain(carrier_freq) + self.atten_return_warm.gain_meas(carrier_freq)
        
        return return_gain
    
    
    def output_noise(self, carrier_freq, spectral_freq, carrier_power_dbm):
        
        n_dac = self.ad9082.dac_noise(spectral_freq, carrier_power_dbm)
        n_dac_output = to_dbm(n_dac) + self.input_gain(carrier_freq) + self.return_gain(carrier_freq)
        
        # noise of the attenuators at the LNA
        natten300K_lna = to_dbm(self.atten_300K.noise()) + self.atten_4K.gain_meas(carrier_freq) + self.atten_still.gain_meas(carrier_freq) + self.atten_mxc.gain_meas(carrier_freq)
        natten4K_lna = to_dbm(self.atten_4K.noise()) + self.atten_still.gain_meas(carrier_freq) + self.atten_mxc.gain_meas(carrier_freq)
        nattenstill_lna = to_dbm(self.atten_still.noise()) + self.atten_mxc.gain_meas(carrier_freq)
        nattenmxc_lna = to_dbm(self.atten_mxc.noise())
        nattentotal_lna = to_W(nattenstill_lna) + to_W(nattenmxc_lna) + to_W(natten4K_lna) + to_W(natten300K_lna)

        # noise of the amplifiers on the return line
        n_wa1 = to_dbm(self.wa1.noise(carrier_freq)) + self.wa1.gain(carrier_freq) + self.wa2.gain(carrier_freq) + self.warm_cables_return.gain(carrier_freq)
        n_wa2 = to_dbm(self.wa2.noise(carrier_freq)) + self.wa2.gain(carrier_freq) + self.warm_cables_return.gain(carrier_freq)
        n_lna = to_dbm(self.lna.noise(carrier_freq)) + self.lna.gain(carrier_freq) + self.wa1.gain(carrier_freq) + self.wa2.gain(carrier_freq) + self.cryo_cables_return.gain(carrier_freq) + self.warm_cables_return.gain(carrier_freq) +self.atten_return_warm.gain_meas(carrier_freq)
        nattenreturn = self.atten_return_warm.noise()

        # totals at output
        nattentotal_out = to_dbm(nattentotal_lna) + self.return_gain(carrier_freq)
        noise_total = to_W(n_dac_output) + to_W(nattentotal_out) + to_W(n_wa1) + to_W(n_wa2) + to_W(n_lna) + nattenreturn
        
        return noise_total
