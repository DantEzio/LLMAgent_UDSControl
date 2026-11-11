# -*- coding: utf-8 -*-
"""SWMM closed-loop simulation environment (based on pyswmm + swmm_api).

Purpose
-------
Wraps the SWMM network model as a "reinforcement-learning-style" environment reused by all
controllers in step1~step4 (rule control BC / MPC / AgenticAI-BC):
    environment = scenario rainfall + inp network + control step,
    each ``step(action)`` call injects pump actions, advances the simulation and returns
    the observation, reward and done flag.

Main interfaces
---------------
get_step_results(...)   extract step overflow/CSO metrics and reward
get_state(...)          assemble the observation vector
SWMM_ENV(params)        construct the environment (see the __init__ docstring for params)
env.reset(rain, ...)    load this event's rainfall and initialize the simulation
env.step(action)        execute one control step

Notes
-----
- The internal pyswmm Simulation must be closed explicitly at the end of each event; otherwise
  the next construction raises MultiSimulationError because of leftover SWMM DLL state;
- The units of observations/rewards are determined by ``config`` (reward_targets etc.); when
  changing them, update the assumptions in time_config and the main_* scripts accordingly.

Implemented with pyswmm; can be adapted to any SWMM inp file.
"""
import os
os.environ['CONDA_DLL_SEARCH_MODIFICATION_ENABLE']="1"
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
sys.path.append(current_dir)

import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

import numpy as np
#import pyswmm.toolkitapi as tkai

from swmm_api.input_file import read_inp_file
from pyswmm import Simulation,Links,Nodes,RainGages,SystemStats
from swmm_api.input_file.sections.others import TimeseriesData
from swmm_api.input_file.section_labels import TIMESERIES

import matplotlib.pyplot as plt
import datetime
import yaml
import shutil 


def get_step_results(results,nodes,links,rgs,sys,config,params):
    
    # Get the reward
    """Extract overflow/CSO metrics and the reward for the current simulation step.

    Args:
        results: Result container (cumulative overflow, CSO, etc.).
        nodes, links, rgs: Current pyswmm node/link/rain-gage objects.
        sys: pyswmm SystemStats, providing system-wide statistics.
        config: Reward weights and target configuration.
        params: Environment parameters (basin design depths, pump indices, etc.).

    Returns:
        Step increments of flooding and CSO plus intermediate values for later accumulation.
    """
    delt_flooding,delt_CSO,CSOtem,delt_Qtw=0,0,0,0  
    for _temp in config['reward_targets']:
        if _temp[1] == 'flooding':
            if _temp[0] == 'system':
                delt_flooding += sys.routing_stats[_temp[1]] - results['flooding'][-1]
            else:
                delt_flooding += nodes[_temp[0]].statistics['flooding_volume']
            results['flooding'].append(sys.routing_stats[_temp[1]])
        else:
            #cum_cso = sys.routing_stats['outflow']
            CSOtem += nodes[_temp[0]].cumulative_inflow
            # log the cumulative value
            #self.data_log[_temp[1]][_temp[0]].append(cum_cso)
    delt_CSO = CSOtem - results['CSO'][-1]
    results['CSO'].append(CSOtem)
    
    Qtw = (sys.routing_stats['dry_weather_inflow']
                +sys.routing_stats['wet_weather_inflow']
                +sys.routing_stats['groundwater_inflow']
                +sys.routing_stats['II_inflow'])
    delt_Qtw = Qtw - results['inflow'][-1]
    results['inflow'].append(Qtw)
    
    #flooding time and cso time
    floodingt, delt_flooding_time = 0,0
    for n in nodes:
        if n.statistics['flooding_duration'] >= floodingt:
            floodingt = n.statistics['flooding_duration']
    delt_flooding_time = floodingt - results['total_flooding_time'][-1]
    results['total_flooding_time'].append(floodingt)
    
    delt_cso_time = 0
    if delt_CSO > 0:
        delt_cso_time = params['advance_seconds']/3600
    results['total_CSO_time'].append(results['total_CSO_time'][-1]+delt_cso_time)

    time = len(results['total_CSO_time']) * 1
    
    # 3 types of reward
    if params['reward_type'] == '1':
        #[0,1]
        if results['inflow'][-1] == 0:
            reward = 1
        else:
            reward = 1 - delt_flooding / delt_Qtw - delt_CSO / delt_Qtw
    elif params['reward_type'] == '2':
        if results['inflow'][-1] == 0:
            reward = 0
        else:
            reward = - (1/(results['inflow'][-1])) * ((delt_flooding * results['total_flooding_time'][-1] + delt_flooding_time * results['flooding'][-1]) 
                                        + (delt_CSO * results['total_CSO_time'][-1] + delt_cso_time * results['CSO'][-1]))
    elif params['reward_type'] == '3':
        if results['inflow'][-1] == 0 or delt_Qtw == 0:
            reward = 0
        else:
            reward = 1 / (1 + delt_flooding/delt_Qtw + delt_CSO/delt_Qtw) - 1
    
    else:
        # maybe the real derivate
        if results['inflow'][-1] == 0:
            reward = 0
        else:
            df_flooding = delt_flooding * results['total_flooding_time'][-1] + delt_flooding_time * results['flooding'][-1]
            f_flooding = results['total_flooding_time'][-1] * results['flooding'][-1]
            dm_flooding = Qtw + delt_Qtw * time
            m_flooding = Qtw * time
            dsev_flooding = (df_flooding * m_flooding - dm_flooding * f_flooding)/(m_flooding * m_flooding)

            df_cso = delt_CSO * results['total_CSO_time'][-1] + delt_cso_time * results['CSO'][-1]
            f_cso = results['total_CSO_time'][-1] * results['CSO'][-1]
            dm_cso = Qtw + delt_Qtw * time
            m_cso = Qtw * time
            dsev_cso = (df_cso * m_cso - dm_cso * f_cso)/(m_cso * m_cso)

            reward = -dsev_flooding - dsev_cso
            # Lower flow differences are better
    
    return results, reward


def get_state(node_idname,pipe_idname,nodes,links):
    # Save all node depths and flows for the Koopman calculation
    """Concatenate node depths and link flows in a fixed order to form the current observation vector.

    Args:
        node_idname: List of node names included in the observation.
        pipe_idname: List of link names included in the observation.
        nodes, links: pyswmm object collections.

    Returns:
        list[float]: Observation vector.
    """
    xtem,intem = [],[]
    for nodename in node_idname:
        xtem.append(nodes[nodename].depth)
        intem.append(nodes[nodename].lateral_inflow)
    for linkname in pipe_idname:
        xtem.append(links[linkname].flow)
    return xtem,intem
    

class SWMM_ENV:
    #can be used for every SWMM inp
    """SWMM closed-loop simulation environment.

    Encapsulates the full interaction flow for one event: ``reset()`` loads rainfall and
    initializes the model, ``step(action)`` executes one control step and returns
    (next_state, reward, done, info).
    The internal pyswmm Simulation must be closed explicitly at the end of each event; otherwise
    the next simulation raises MultiSimulationError because of leftover SWMM DLL state.
    """
    def __init__(self,params):
        '''
        params: a dictionary with input
        orf: original file of swmm inp
        control_asset: list of contorl objective, pumps' name
        advance_seconds: simulation time interval
        flood_nodes: selected node for flooding checking
        '''
        self.params = params
    
    
    def reset(self,rain,rainid,trainlog,root):
        
        """Reset the environment: apply this event's rainfall, rebuild the SWMM simulation objects and
        advance to the first control time.

        Args:
            rain: Rainfall series (mm/step or mm/hr, depending on config).
            rainid: Rainfall ID (used for logs and curve filenames).
            trainlog: Train/test flag.
            root: Root directory for result output.

        Returns:
            Initial observation vector.
        """
        self.config = yaml.load(open(self.params['parm']+".yaml"), yaml.FullLoader)
        #self.revise_config(Bselected_name)
        
        inp = read_inp_file(self.params['orf']+'.inp')
        # All pipe and node names
        self.pipe_idname = {}
        pid = 1
        for k in inp.CONDUITS.keys():
            self.pipe_idname[k] = pid
            pid += 1

        self.node_idname = {}
        nid = 1
        for k in inp.JUNCTIONS.keys():
            self.node_idname[k] = nid
            nid += 1

        # rainfall data
        inp[TIMESERIES]['rainfall']=TimeseriesData('rainfall',rain[rainid])

        if trainlog:
            root += '/SWMM_control/_teminp'
        else:
            root += '/SWMM_control/_temtestinp'
        inp.write_file(root+'/'+self.params['orf_save']+str(rainid)+'_rain.inp')
        self.sim=Simulation(root+'/'+self.params['orf_save']+str(rainid)+'_rain.inp')
        self.sim.start()
        
        # Get results and record CSO and flooding
        self.results = {}
        # Record total CSO, flooding and res
        self.results['CSO'], self.results['flooding'], self.results['inflow'] = [0], [0], [0]
        self.results['total_flooding_time'], self.results['total_CSO_time'] = [0], [0]
        self.results['res'] = [0]
        self.results['state'], self.results['action'], self.results['rewards'] = [], [], []
        self.results['rewards_conb'],self.results['rewards_obs'] = [], []
        self.results['all_state'],self.results['all_inflow'] = [], []

        # One step forward
        if self.params['advance_seconds'] is None:
            self.sim._model.swmm_step()
        else:
            self.sim._model.swmm_stride(self.params['advance_seconds'])

            
        #obtain states and reward term by yaml (config)
        nodes = Nodes(self.sim)
        links = Links(self.sim)
        rgs = RainGages(self.sim)
        
        
        # Only the last step of the state is used
        states = []
        for _temp in self.config["states"]:
            if _temp[1] == 'depthN':
                states.append(nodes[_temp[0]].depth)
            elif _temp[1] == 'flow':
                states.append(links[_temp[0]].flow)
            elif _temp[1] == 'inflow':
                states.append(nodes[_temp[0]].total_inflow)
            else:
                states.append(rgs[_temp[0]].rainfall)
        
        if self.params['istest']:
            xtem,intem = get_state(self.node_idname,self.pipe_idname,nodes,links)
            self.results['all_state'].append(xtem)
            self.results['all_inflow'].append(intem)

        return states
        
    def step(self,action):
        # Get the simulation results
        """Execute one control step.

        Args:
            action: Pump action vector (0=off, 1=on).

        Returns:
            tuple: (next_state, reward, done, info); info contains this step's flooding/CSO details.
        """
        nodes = Nodes(self.sim)
        links = Links(self.sim)
        rgs = RainGages(self.sim)
        sys = SystemStats(self.sim)

        #obtain states and reward term by yaml (config)
        states = []
        for _temp in self.config["states"]:
            if _temp[1] == 'depthN':
                states.append(nodes[_temp[0]].depth)
            elif _temp[1] == 'flow':
                states.append(links[_temp[0]].flow)
            elif _temp[1] == 'inflow':
                states.append(nodes[_temp[0]].total_inflow)
            else:
                states.append(rgs[_temp[0]].rainfall)
        
        # Apply the control actions
        for item,a in zip(self.config['action_assets'],action):
            links[item].target_setting = a

        # Advance the simulation by one step
        if self.params['advance_seconds'] is None:
            time = self.sim._model.swmm_step()
        else:
            time = self.sim._model.swmm_stride(self.params['advance_seconds'])
        #self.t.append(self.sim._model.getCurrentSimulationTime())
        done = False if time > 0 else True
        
        # Get the reward and results
        self.results, reward = get_step_results(self.results,nodes,links,rgs,sys,self.config,self.params)
        
        if self.params['istest']:
            self.results['state'].append(states)
            self.results['action'].append(action)
            self.results['rewards'].append(reward)
        
            xtem,intem = get_state(self.node_idname,self.pipe_idname,nodes,links)
            self.results['all_state'].append(xtem)
            self.results['all_inflow'].append(intem)
        
        else:
            reward = reward
            self.results['state'].append(states)
            self.results['action'].append(action)
            self.results['rewards'].append(reward)
               
        # Detect the end of rainfall
        if done:
            self.sim._model.swmm_end()
            self.sim._model.swmm_close()
        return states,reward,self.results,done
    
        
            
