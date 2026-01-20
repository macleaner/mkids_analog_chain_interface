from hidfmux.core.resources.analog_chain import AnalogChain
import hidfmux.core.resources.hardware_models as hardware_models
import hidfmux.core.utils.transferfunctions as transferfunctions
from hidfmux.core.utils.transferfunctions import to_dbm, to_W



class Default(AnalogChain):
    '''
    A very simple analog chain class, emulating a lossless SMA desktop loopback configuration.
    '''
    
    def __init__(self):

        self.ad9082 = hardware_models.AD9082()
                
        
    def input_gain(self, carrier_freq):
                
        return 0
    
    
    def return_gain(self, carrier_freq):
        
        return 0
    
    
    def output_noise(self, carrier_freq, spectral_freq, carrier_power_dbm):
        
        n_dac = self.ad9082.dac_noise(spectral_freq, carrier_power_dbm)
        n_dac_output = to_dbm(n_dac) + self.input_gain(carrier_freq) + self.return_gain(carrier_freq)
        
        n_adc = self.ad9082.adc_noise()
        
        # totals at output:
        noise_total = to_W(n_dac_output) + n_adc
        
        return noise_total
