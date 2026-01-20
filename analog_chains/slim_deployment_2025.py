import numpy as np
import os
import pickle

import hidfmux.core.utils.user_config as config

from hidfmux.core.resources.analog_chain import AnalogChain
import hidfmux.core.resources.hardware_models as hardware_models
import hidfmux.core.utils.transferfunctions as transferfunctions
from hidfmux.core.utils.transferfunctions import to_dbm, to_W


    
    
class SLIM_deployment_AC_v1(AnalogChain):
    '''
    more or less as above but make the cabling objects more modular to accommodate
    building one of these for each line in the cryostat fml
    '''
    
    def __init__(self):

        self.ad9082 = hardware_models.AD9082()
        
        # input attenuation & amplification
        self.filter_hp = hardware_models.FilterHP_VHF1910p()
        # self.atten_300K = hardware_models.Attenuator(-10, 300)
        # self.wa_input = hardware_models.ZX60_3018Gplus()
        
        # in cryostat
        self.atten_4K = hardware_models.Attenuator(-20, 4)
        self.atten_GGG = hardware_models.Attenuator(-10, 0.5)
        self.atten_FAA = hardware_models.Attenuator(0, 0.15) 
        
        # input cables
        self.patch_cables_in = hardware_models.SMA_RG58C_cables(length_m=0.3)
        self.warm_cables_in = hardware_models.SMA_FM_F141_cables(length_m=3.5)
        
        self.cables_300to50 = hardware_models.BCB014_SS085_cryo(length_m=0.3, temperature=300)
        self.cables_50to4 = hardware_models.BCB014_SS085_cryo(length_m=0.5, temperature=4)
        self.cables_4toGGG = hardware_models.BCB029_SS034_cryo(length_m=0.3, temperature=4)
        self.cables_GGGtoFAA = hardware_models.BCB029_SS034_cryo(length_m=0.3, temperature=0.5)
        
        
        # return amplifiers etc
        self.lna = hardware_models.ASU_3GHz_LNA()
        self.wa1 = hardware_models.ZX60_3018Gplus()
        self.wa2 = hardware_models.ZX60_3018Gplus()
        self.warm_cables_return = hardware_models.SMA_FM_F141_cables(length_m=3.5)
        self.patch_cable_wa1_to_wa2 = hardware_models.SMA_RG174A_cables(length_m=0.15)
        self.patch_cable_wa2_to_panel = hardware_models.SMA_RG58C_cables(length_m=0.3)
        self.patch_cable_panel = hardware_models.SMA_RG174A_cables(length_m=0.6)
        self.patch_cable_panel_iceboard = hardware_models.SMA_RG58C_cables(length_m=0.3)
        
        self.cables_FAAtoGGG = hardware_models.BCB012_NbTi034_cryo(length_m=0.3, temperature=0.3)
        self.cables_GGGto4 = hardware_models.BCB012_NbTi034_cryo(length_m=0.3, temperature=4)
        self.cables_4to50 = hardware_models.BCB014_SS085_cryo(length_m=0.5, temperature=50)
        self.cables_50to300 = hardware_models.BCB014_SS085_cryo(length_m=0.3, temperature=300)

        # probably it will be useful to have some collections of objects...?
        self.all_cold_cables_in = [self.cables_300to50, self.cables_50to4, self.cables_4toGGG, self.cables_GGGtoFAA]
        self.all_cold_cables_return = [self.cables_FAAtoGGG, self.cables_GGGto4, self.cables_4to50, self.cables_50to300]
        self.all_patch_cables_return = [self.warm_cables_return, self.patch_cable_wa1_to_wa2, self.patch_cable_wa2_to_panel, self.patch_cable_panel, self.patch_cable_panel_iceboard]
        
        
    def input_gain(self, carrier_freq):
        
        warm_component_gain = self.filter_hp.gain(carrier_freq)
        warm_cable_gain = self.patch_cables_in.gain(carrier_freq) + self.warm_cables_in.gain(carrier_freq)

        cold_component_gain = self.atten_4K.gain(carrier_freq) + self.atten_GGG.gain(carrier_freq) + self.atten_FAA.gain(carrier_freq)
        cold_cable_gain = self.cables_300to50.gain(carrier_freq) + self.cables_50to4.gain(carrier_freq) + self.cables_4toGGG.gain(carrier_freq) + self.cables_GGGtoFAA.gain(carrier_freq)
        
        return warm_component_gain + warm_cable_gain + cold_component_gain + cold_cable_gain
    
    
    def return_gain(self, carrier_freq):
        
        cold_component_gain = self.lna.gain(carrier_freq)
        cold_cable_gain = self.cables_FAAtoGGG.gain(carrier_freq) + self.cables_GGGto4.gain(carrier_freq) + self.cables_4to50.gain(carrier_freq) + self.cables_50to300.gain(carrier_freq) 
        
        warm_component_gain = self.wa1.gain(carrier_freq) + self.wa2.gain(carrier_freq)
        warm_cable_gain = self.warm_cables_return.gain(carrier_freq) + self.patch_cable_wa1_to_wa2.gain(carrier_freq) + self.patch_cable_wa2_to_panel.gain(carrier_freq) + self.patch_cable_panel.gain(carrier_freq) + self.patch_cable_panel_iceboard.gain(carrier_freq)
        
        return cold_component_gain + cold_cable_gain + warm_component_gain + warm_cable_gain
    
    
    def output_noise(self, carrier_freq, spectral_freq, carrier_power_dbm):

        '''
        n_dac = self.ad9082.dac_noise(spectral_freq, carrier_power_dbm)
        n_dac_lna = to_dbm(n_dac) + self.input_gain(carrier_freq)
        n_dac_output = n_dac_lna + self.return_gain(carrier_freq)

        # noise of the attenuators and input amplifier at the LNA
        input_cable_gain = self.warm_cables_in.gain(carrier_freq) + self.cables_300to50.gain(carrier_freq) + self.cables_50to4.gain(carrier_freq) + self.cables_4toGGG.gain(carrier_freq) + self.cables_GGGtoFAA.gain(carrier_freq)
        
        n_atten_300K_lna = to_dbm(self.atten_300K.noise()) + self.wa_input.gain(carrier_freq) + input_cable_gain
        n_wainput_lna = to_dbm(self.wa_input.noise(carrier_freq)) +self.wa_input.gain(carrier_freq) + input_cable_gain
        natten_FAA_lna = to_dbm(self.atten_FAA.noise())
        # total of component noise not including LNA itself or dac
        n_components_at_lna = to_dbm( to_W(natten_FAA_lna) + to_W(n_atten_300K_lna) + to_W(n_wainput_lna))
        # LNA itself
        n_lna = to_dbm(self.lna.noise(carrier_freq))
        n_total_at_lna = to_dbm( to_W(n_dac_lna) + to_W(n_lna) + to_W(n_components_at_lna))

        # # noise of the amplifiers on the return line
        n_wa1_output = to_dbm(self.wa1.noise(carrier_freq)) + self.wa1.gain(carrier_freq) + self.wa2.gain(carrier_freq)
        n_wa2_output = to_dbm(self.wa2.noise(carrier_freq)) + self.wa2.gain(carrier_freq)
        n_lna_output = to_dbm(self.lna.noise(carrier_freq)) + self.return_gain(carrier_freq)
        n_wainput_output = n_wainput_lna + self.return_gain(carrier_freq)

        noise_total_output = to_dbm( to_W(n_total_at_lna + self.return_gain(carrier_freq)) + to_W(n_wa1_output))

        
        return frange, noise_total_output, n_dac_output
        '''
        return 0 ### todo






class SLIM_deployment_AC_2025(AnalogChain):
    '''
    possible 2025 deployment analog chain
    key difference: remove some cold attenuators on the input
    maybe also remove the first stage amp...?
    '''
    
    def __init__(self):

        self.ad9082 = hardware_models.AD9082()
        
        # input attenuation & amplification
        self.filter_hp = hardware_models.FilterHP_VHF1910p()
        # self.atten_300K = hardware_models.Attenuator(-10, 300)
        # self.wa_input = hardware_models.ZX60_3018Gplus()
        
        # in cryostat
        self.atten_4K = hardware_models.Attenuator(-10, 4)
        self.atten_GGG = hardware_models.Attenuator(0, 0.7)
        self.atten_FAA = hardware_models.Attenuator(-10, 0.15) 
        
        # input cables
        self.warm_cables_in = hardware_models.SMA_FM_F141_cables(length_m=3)
        
        self.cables_300to50 = hardware_models.SMA_SS086_cryo(length_m=0.3, temperature=300)
        self.cables_50to4 = hardware_models.SMA_SS219_cryo(length_m=0.5, temperature=4)
        self.cables_4toGGG = hardware_models.SMA_SS219_cryo(length_m=0.3, temperature=4)
        self.cables_GGGtoFAA = hardware_models.SMA_SS086_cryo(length_m=0.25, temperature=0.5)
        
        
        # return amplifiers etc
        self.lna = hardware_models.ASU_3GHz_LNA()
        self.wa1 = hardware_models.ZX60_3018Gplus()
        self.wa2 = hardware_models.ZX60_3018Gplus()
        self.warm_cables_return = hardware_models.SMA_FM_F141_cables(length_m=3)
        
        self.cables_FAAtoGGG = hardware_models.SMA_NbTi086_cryo(length_m=0.25, temperature=0.3)
        self.cables_GGGto4 = hardware_models.SMA_NbTi086_cryo(length_m=0.5, temperature=4)
        self.cables_4to50 = hardware_models.SMA_CuNi086_cryo(length_m=0.5, temperature=50)
        self.cables_50to300 = hardware_models.SMA_SS086_cryo(length_m=0.3, temperature=300)
        
#         self.atten_return_warm = hardware_models.Attenuator(-9, 300) ### is this present?
        
    def input_gain(self, carrier_freq):
        
        outside_cs_components = self.filter_hp.gain(carrier_freq) #+ self.wa_input.gain(carrier_freq) + self.atten_300K.gain_meas(carrier_freq)
        
        inside_cs_components = self.atten_4K.gain_meas(carrier_freq) + self.atten_GGG.gain_meas(carrier_freq) + self.atten_FAA.gain_meas(carrier_freq)
        
        cable_gain = self.warm_cables_in.gain(carrier_freq) + self.cables_300to50.gain(carrier_freq) + self.cables_50to4.gain(carrier_freq) + self.cables_4toGGG.gain(carrier_freq) + self.cables_GGGtoFAA.gain(carrier_freq)
        
        return outside_cs_components + inside_cs_components + cable_gain
    
    
    def return_gain(self, carrier_freq):
        
        amplifier_gain = self.lna.gain(carrier_freq) + self.wa1.gain(carrier_freq) + self.wa2.gain(carrier_freq)
        cable_gain = self.cables_FAAtoGGG.gain(carrier_freq) + self.cables_GGGto4.gain(carrier_freq) + self.cables_4to50.gain(carrier_freq) + self.cables_50to300.gain(carrier_freq) + self.warm_cables_return.gain(carrier_freq)
        
        return amplifier_gain + cable_gain
    
    
    def output_noise(self, carrier_freq, spectral_freq, carrier_power_dbm):

        return 0
