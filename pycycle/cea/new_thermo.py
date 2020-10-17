import openmdao.api as om

from pycycle.constants import AIR_MIX
from pycycle import cea
from pycycle.cea import chem_eq
from pycycle.cea.static_ps_calc import PsCalc
from pycycle.cea.static_ps_resid import PsResid

from pycycle.cea.unit_comps import EngUnitStaticProps, EngUnitProps



class Thermo(om.Group):

    def initialize(self):
        self.options.declare('fl_name',
                              default="flow",
                              desc='Flowstation name of the output flow variables')
        self.options.declare('mode',
                              desc='Set the computation mode for the thermodynamics',
                              default='total_TP',
                              values=('total_TP', 'total_SP', 'total_hP', 
                                    'static_MN', 'static_A', 'static_Ps'))
        # thermo_dict should be a dictionary containing all the information needed to setup
        # the thermo calculations:
        #       - For CEA this would be the elements and thermo_data
        #       - For Ideal this would be gamma, MW, h_base, T_base, Cp, S_data
        #       - For Tabular this would be the thermo data table
        # The user should define one or more of these dictionaries at the top of their model
        # then pass them into the individual componenents
        self.options.declare('thermo_dict',
                              desc='Defines the thermodynamic data to be used in computations')

    def setup(self):
        method = self.options['thermo_dict']['method']
        mode = self.options['mode']

        therm_dict = self.options['thermo_dict']

        # Instantiate components based on method for calculating the thermo properties.
        # All these components should compute the properties in a TP mode.
        if method == 'CEA':
            cea_data = cea.species_data.Thermo(therm_dict['thermo_data'], 
                                                therm_dict['elements'])

            base_thermo = chem_eq.SetTotalTP(thermo=cea_data)

        # elif method == 'Ideal':
        #     # base_thermo = IdealThermo(thermo_data=xx)
        #     pass
        # elif method == 'Tabular':
        #     # base_thermo = TabularThermo(thermo_data=xx)
        #     pass

        in_vars = ('T', 'b0')
        # TODO: remove 'n', 'n_moles' variable from flow station
        out_vars = ('gamma', 'Cp', 'Cv', 'rho', 'R', 'n', 'n_moles')

        if 'TP' in mode: 
            in_vars += ('P', )
            out_vars += ('S', 'h')
        if 'hP' in mode: 
            # leave h unpromoted to connect to balance lhs
            in_vars += ('P', )
            out_vars += ('S',) 
        if 'SP' in mode: 
            in_vars += ('P', )
            # leave S unpromoted to connect to balance lhs
            out_vars += ('h',)

        if 'static' in mode: 
            in_vars += (('P', 'Ps'),)
            out_vars += ('h', )
        
        self.add_subsystem('base_thermo', base_thermo, 
                           promotes_inputs=in_vars, 
                           promotes_outputs=out_vars)

        # TODO: merge this into base_thermon from CEA
        
       
        
        if 'static' in mode:  
            in_vars += (('P', 'Ps'), ) # promote the P as the static Ps
           

       

        # Add implicit components/balances to depending on the mode and connect them to
        # the properties calculation components
        if mode != "total_TP": 
            bal = self.add_subsystem('balance', om.BalanceComp(), promotes_outputs=['T'])

            # all static calcs seek to match a given entropy, similar to a total_PS
            if ('SP' in mode) or ('static' in mode):
                bal.add_balance('T', val=500., units='degK', eq_units='cal/(g*degK)', lower=100.)
                self.promotes('balance', inputs=[('rhs:T','S')])
                self.connect('base_thermo.S', 'balance.lhs:T')
            elif 'hP' in mode: 
                bal.add_balance('T', val=500., units='degK', eq_units='cal/g', lower=100.)
                self.promotes('balance', inputs=[('rhs:T','h')])
                self.connect('base_thermo.h', 'balance.lhs:T')

            ##############################################
            #extra stuff for statics beyond the S balance
            ##############################################
            if 'Ps' in mode: 
                self.add_subsystem('ps_calc', PsCalc(),
                                   promotes_inputs=['gamma', 'n_moles', 'ht', 'W', 'rho',
                                                    ('Ts', 'T'), ('hs', 'h')],
                                   promotes_outputs=['MN', 'V', 'Vsonic', 'area']
                                   )
            elif 'A' in mode: 
                self.add_subsystem('ps_resid', PsResid(mode='area'),
                                   promotes_inputs=['ht', 'n_moles', 'gamma', 'W',
                                                    'rho', 'area', 'guess:*', ('Ts', 'T'), ('hs', 'h')],
                                   promotes_outputs=['V', 'Vsonic', 'MN', 'Ps']) 

            elif 'MN' in mode: 
                self.add_subsystem('ps_resid', PsResid(mode='MN'),
                                   promotes_inputs=['ht', 'n_moles', 'gamma', 'W',
                                                    'rho', 'MN', 'guess:*', ('Ts', 'T'), ('hs', 'h')],
                                   promotes_outputs=['V', 'Vsonic', 'area', 'Ps']) 

        # TODO: Move the newton stuff into a convergence sub-group that doesn't include this 
        # not a big deal right now though
        # Compute English units and promote outputs to the station name


        in_vars = ('T', 'P', 'h', 'S', 'gamma', 'Cp', 'Cv', 'rho', 'n', 'n_moles', 'b0', 'R')
        if 'static' in mode: 
        # need to redefine this so that P gets promoted as P. 
            in_vars = ('T', ('P', 'Ps'), 'h', 'S', 'gamma', 'Cp', 'Cv', 'rho', 'n', 'n_moles', 'R')

        fl_name = self.options['fl_name']
        # TODO: remove need for thermo specific data in the flow components
        self.add_subsystem('flow', EngUnitProps(thermo=cea_data, fl_name=fl_name),
                           promotes_inputs=in_vars,
                           promotes_outputs=(f'{fl_name}:*',))


        if 'static' in mode:
            in_vars = ('area', 'W', 'V', 'Vsonic', 'MN')
            # TODO: remove need for thermo specific data in the flow components
            eng_units_statics = EngUnitStaticProps(thermo=cea_data, fl_name=fl_name)
            self.add_subsystem('flow_static', eng_units_statics,
                               promotes_inputs=in_vars,
                               promotes_outputs=(f'{fl_name}:*',))

            self.set_input_defaults('W', val=1., units='kg/s')
            self.set_input_defaults('Ps', 1, units='bar')

            if 'A' in mode: 
                self.set_input_defaults('area', 1., units='m**2')

        else: 
            self.set_input_defaults('P', 1, units='bar')

        if 'TP' in mode: 
            self.set_input_defaults('T', 273, units='degK')
        else: 
            if 'hP' in mode: 
                self.set_input_defaults('h', 1., units='cal/g')
            if 'SP' in mode or 'static' in mode: 
                self.set_input_defaults('S', 1., units='cal/(g*degK)')


        newton = self.nonlinear_solver = om.NewtonSolver()
        newton.options['maxiter'] = 100
        newton.options['atol'] = 1e-10
        newton.options['rtol'] = 1e-10
        newton.options['stall_limit'] = 4
        newton.options['stall_tol'] = 1e-10
        newton.options['solve_subsystems'] = True

        newton.options['iprint'] = 2

        self.options['assembled_jac_type'] = 'dense'
        self.linear_solver = om.DirectSolver()

        # ln_bt = newton.linesearch = om.BoundsEnforceLS()
        ln_bt = newton.linesearch = om.ArmijoGoldsteinLS()
        ln_bt.options['maxiter'] = 2
        ln_bt.options['iprint'] = -1



if __name__ == "__main__": 
    from pycycle.cea import species_data
    from pycycle.constants import CO2_CO_O2_MIX

    p = om.Problem()

    p.model = Thermo(mode='total_TP', 
                     thermo_dict={'method':'CEA', 
                                  'elements': CO2_CO_O2_MIX, 
                                  'thermo_data': species_data.co2_co_o2 })

    p.setup()
    # p.final_setup()


    # p.set_val('b0', [0.02272211, 0.04544422])
    p.set_val('T', 4000, units='degK')
    p.set_val('P', 1.034210, units='bar')

    p.run_model()

    # p.model.list_inputs(prom_name=True, print_arrays=True)
    # p.model.list_outputs(prom_name=True, print_arrays=True)

    n = p['base_thermo.n']
    n_moles = p['base_thermo.n_moles']

    print(n/n_moles) # [0.62003271, 0.06995092, 0.31001638]
    print(n_moles) # 0.03293137

    gamma = p['flow:gamma']
    print(gamma) # 1.19054697
