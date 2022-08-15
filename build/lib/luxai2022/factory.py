from __future__ import annotations
from collections import deque
import time
from typing import List
import numpy as np
from luxai2022.config import EnvConfig
from luxai2022.map.board import Board
from luxai2022.map.position import Position
from luxai2022.team import Team
from luxai2022.unit import UnitCargo
from luxai2022.actions import move_deltas

def compute_water_info(init: np.ndarray, MIN_LICHEN_TO_SPREAD: int, lichen: np.ndarray, lichen_strains: np.ndarray, strain_id: int, forbidden: np.ndarray):
    # TODO - improve the performance here with cached solution
    frontier = deque(init)
    seen = set()
    grow_lichen_positions = set()
    H, W = lichen.shape
    while len(frontier) > 0:
        pos = frontier.popleft()
        if (pos[0], pos[1]) in seen: continue
        seen.add((pos[0], pos[1]))
        if forbidden[pos[1], pos[0]]: 
            continue
        pos_lichen = lichen[pos[1], pos[0]]
        # check for surrounding tiles with lichen and no incompatible lichen strains, grow on those
        can_grow = True
        for move_delta in move_deltas[1:]:
            check_pos = pos + move_delta
            if (check_pos[0], check_pos[1]) in seen: continue
            # check surrounding tiles on the map
            if check_pos[0] < 0 or check_pos[1] < 0 or check_pos[0] >= W or check_pos[1] >= H: continue
            adj_strain = lichen_strains[check_pos[1], check_pos[0]]
            if adj_strain != strain_id:
                if adj_strain != -1:
                    # adjacent tile is not empty and is not a strain this factory owns.
                    can_grow = False
            else:
                # adjacent tile has our own strain, we can grow here too
                frontier.append(check_pos)

            if pos_lichen >= MIN_LICHEN_TO_SPREAD and adj_strain == -1:
                # empty tile and current tile has enough lichen to spread
                frontier.append(check_pos)
                
        if can_grow:
            grow_lichen_positions.add((pos[0], pos[1]))
    return grow_lichen_positions


class Factory:
    def __init__(self, team: Team, unit_id: str, num_id: int) -> None:
        self.team_id = team.team_id
        self.team = team
        self.unit_id = unit_id
        self.pos = Position(np.zeros(2, dtype=int))
        self.power = 0
        self.cargo = UnitCargo()
        self.num_id = num_id
        self.action_queue = [] # TODO can we queue actions or are factories outside of max control limit
        self.grow_lichen_positions = None

    def refine_step(self, config: EnvConfig):
        consumed_ice = min(self.cargo.ice, config.FACTORY_PROCESSING_RATE_WATER)
        consumed_ore = min(self.cargo.metal, config.FACTORY_PROCESSING_RATE_METAL)

        self.cargo.ice -= consumed_ice
        self.cargo.ore -= consumed_ore
        
        # TODO - are we rounding or doing floats or anything?
        self.cargo.water += consumed_ice / config.ICE_WATER_RATIO
        self.cargo.metal += consumed_ore / config.ORE_METAL_RATIO

    def cache_water_info(self, board: Board, env_cfg: EnvConfig):
        # TODO this can easily be a fairly slow function, can we make it much faster?
        # Caches information about which tiles lichen can grow on for this factory
        
        # perform a BFS from the factory position and look for non rubble, non factory tiles.
        # find the current frontier from 4 starting positions x marked below
        """
             x
           _ _ _
          |     |
        x |     | x
          |_ _ _|
             x
        
        """
        forbidden = (board.rubble > 0) | (board.factory_occupancy_map != -1)
        init_arr = np.stack([self.pos.pos + np.array([0, -2]), self.pos.pos + np.array([2, 0]), self.pos.pos + np.array([0, 2]), self.pos.pos + np.array([-2, 0])])
        self.grow_lichen_positions = compute_water_info(init_arr, env_cfg.MIN_LICHEN_TO_SPREAD, board.lichen, board.lichen_strains, self.num_id, forbidden)
    def water_cost(self, config: EnvConfig):
        return np.ceil(len(self.grow_lichen_positions) / config.LICHEN_WATERING_COST_FACTOR) + 1

    ### Add and sub resource functions copied over from unit.py code, can we consolidate them somewhere?
    def add_resource(self, resource_id, amount):
        if amount < 0: amount = 0
        if resource_id == 0:
            transfer_amount = min(self.cargo_space - self.cargo.ice, amount)
            self.cargo.ice += transfer_amount
        elif resource_id == 1:
            transfer_amount = min(self.cargo_space - self.cargo.ore, amount)
            self.cargo.ore += transfer_amount
        elif resource_id == 2:
            transfer_amount = min(self.cargo_space - self.cargo.water, amount)
            self.cargo.water += transfer_amount
        elif resource_id == 3:
            transfer_amount = min(self.cargo_space - self.cargo.metal, amount)
            self.cargo.metal += transfer_amount
        elif resource_id == 4:
            transfer_amount = min(self.battery_capacity - self.power, amount)
            self.power += transfer_amount
        return transfer_amount
    def sub_resource(self, resource_id, amount):
        # subtract/transfer out as much as you min(have, request)
        if amount < 0: amount = 0
        if resource_id == 0:
            transfer_amount = min(self.cargo.ice, amount)
            self.cargo.ice -= transfer_amount
        elif resource_id == 1:
            transfer_amount = min(self.cargo.ore, amount)
            self.cargo.ore -= transfer_amount
        elif resource_id == 2:
            transfer_amount = min(self.cargo.water, amount)
            self.cargo.water -= transfer_amount
        elif resource_id == 3:
            transfer_amount = min(self.cargo.metal, amount)
            self.cargo.metal -= transfer_amount
        elif resource_id == 4:
            transfer_amount = min(self.power, amount)
            self.power -= transfer_amount
        return transfer_amount




    def state_dict(self):
        return dict(
            pos=self.pos.pos,
            power=self.power,
            cargo=self.cargo.state_dict(),
            unit_id=self.unit_id,
            team_id=self.team_id

        )