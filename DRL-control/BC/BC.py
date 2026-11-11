"""Water-level-threshold rule controller (Baseline Controller, BC).

This module implements the simplest reference controller in the project: it switches pumps
using only current storage/node water levels and preset graded thresholds, without any
prediction or learning. The MPC, DRL and LLM agent methods are all compared against this
rule controller (BC baseline).

Control logic
-------------
Each pump has two water level thresholds (high / low):
  * level >= high threshold            -> pump forced on (1)
  * low threshold <= level < high      -> keep the previous state (hysteresis, avoids frequent switching)
  * level < low threshold              -> pump off (0)

Thresholds scale with the design depth of each basin, so the same rules work for basins of different sizes.

Coordinate convention
---------------------
See the inline comments in BC_rule for the indices of state / nodes_depth; pre_action is the
previous 7-pump action vector (0=off, 1=on).

Used by
-------
- DRL-control/step1-BC-control/main_BCtest.py inlines the same implementation (used by the main flow);
- An early prototype notebook used ``from BC import BC_rule`` directly.
"""

from swmm_api.input_file import read_inp_file
from pyswmm import Simulation,Links,Nodes,RainGages,SystemStats
from swmm_api.input_file.sections.others import TimeseriesData
from swmm_api.input_file.section_labels import TIMESERIES,PUMPS,CONDUITS,OUTFALLS,COORDINATES



def BC_rule(state,nodes_depth,pre_action):
    """Compute the control actions for 7 pumps from the current water levels and the previous actions.

    Parameters
    ----------
    state : sequence[float]
        Current system state; ``state[0]`` is the CC storage depth, ``state[1]`` is the JK storage
        depth, and ``state[-1]`` is an additional observation (same unit as JK).
    nodes_depth : sequence[float]
        Design depths of the basins (used to scale thresholds), in the order CC / JK / AD.
    pre_action : sequence[int]
        Previous 7-pump action (0=off, 1=on), in the order
        [cc_s1, cc_s2, cc_r1, cc_r2, jk_s, jk_r1, jk_r2].

    Returns
    -------
    list[int]
        Current 7-pump action vector, in the same order as ``pre_action``.
    """

    # Pump control levels must be scaled proportionally to the current node depth
    #state[0]:cc-storage depth; state[1]:jk-storage depth
    # CC depth: 2.3; JK depth: 5.8
    #stdlevel = {
    #    'cc_s1':[0.8,0.5],
    #    'jk_s':[4,1]
    #}
    stdlevel = {
        'cc_s1':[nodes_depth[0]*0.8/2.8,nodes_depth[0]*0.5/2.8],
        'cc_s2':[nodes_depth[0]*1.0/2.8,nodes_depth[0]*0.5/2.8],
        'cc_r1':[nodes_depth[0]*1.2/2.8,nodes_depth[0]*0.5/2.8],
        'cc_r2':[nodes_depth[0]*1.4/2.8,nodes_depth[0]*0.5/2.8],
        'jk_s':[nodes_depth[1]*4/5.8,nodes_depth[1]*1/5.8],
        'jk_r1':[nodes_depth[1]*4.2/5.8,nodes_depth[1]*1.2/5.8],
        'jk_r2':[nodes_depth[1]*4.3/5.8,nodes_depth[1]*1.2/5.8],
        'ad_s1':[nodes_depth[2]*0.8/2.8,nodes_depth[2]*0.5/2.8],
    }

    cc_s1 = level_rule(state[0],pre_action[0],stdlevel['cc_s1'])
    cc_s2 = level_rule(state[0],pre_action[1],stdlevel['cc_s2'])
    cc_r1 = level_rule(state[0],pre_action[2],stdlevel['cc_s2'])
    cc_r2 = level_rule(state[0],pre_action[3],stdlevel['cc_s2'])
    jk_s  = level_rule(state[1],pre_action[4],stdlevel['jk_s'])
    jk_r1  = level_rule(state[1],pre_action[5],stdlevel['jk_r1'])
    jk_r2  = level_rule(state[-1],pre_action[6],stdlevel['jk_r1'])
    
    return [cc_s1,cc_s2,cc_r1,cc_r2,jk_s,jk_r1,jk_r2]
    
def level_rule(level,pre_action,stdlevel):
    """Hysteresis water-level rule for a single pump.

    Parameters
    ----------
    level : float
        Current water depth (m) of the basin this pump belongs to.
    pre_action : int
        Previous action of this pump (0=off, 1=on).
    stdlevel : sequence[float]
        ``[high threshold, low threshold]``; above the high threshold the pump is forced on,
        below the low threshold it is forced off, and in between the previous state is kept.

    Returns
    -------
    int
        Current action of this pump (0=off, 1=on).
    """
    cc_a = pre_action
    if level>=stdlevel[0]:
        cc_a = 1
    else:
        if level>=stdlevel[1]:
            if pre_action==0:
                cc_a = 0
            else:
                cc_a = 1
        else:
            cc_a = 0
    return cc_a
