

class AnalogChain:
    '''
    Base class for models of hidfmux analog chains.
    '''
    
    def input_gain(self, carrier_freq):
        pass
    
    def return_gain(self, carrier_freq):
        pass
    
    def output_noise(self, carrier_freq, spectral_freq):
        pass
