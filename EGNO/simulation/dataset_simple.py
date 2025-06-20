import numpy as np
import torch
from pathlib import Path
from utils import conserved_energy_fun
from torch_geometric.utils import to_dense_batch


class NBodyDataset():
    """
    NBodyDataset

    """

    def __init__(self, data_dir, partition='train', max_samples=1e8, dataset="charged", dataset_name="nbody_small",n_balls=5):
        self.partition = partition
        self.data_dir = data_dir
        if self.partition == 'val':
            self.suffix = 'valid'
        else:
            self.suffix = self.partition
        self.dataset_name = dataset_name
        if dataset_name == "nbody":
            self.suffix += f"_{dataset}{n_balls}_initvel1"
        elif dataset_name == "nbody_small" or dataset_name == "nbody_small_out_dist":
            self.suffix += f"_{dataset}{n_balls}_initvel1small"
        else:
            raise Exception("Wrong dataset name %s" % self.dataset_name)
        
        self.n_balls = n_balls
        self.max_samples = int(max_samples)
        self.dataset_name = dataset_name
        self.dataset = dataset
        self.data, self.edges = self.load()
        
    def energy_fun(self, loc, vel, edges, batch=None):
        return conserved_energy_fun(self.dataset, loc, vel, edges, batch=batch)

    def load(self):
        loc = np.load(self.data_dir / f'loc_{self.suffix}.npy') # shape (n_samples, n_timesteps, n_balls, 3)
        vel = np.load(self.data_dir / f'vel_{self.suffix}.npy')
        if loc.shape[-2:] != (self.n_balls, 3):
            # should transpose the last two dimensions
            loc = np.transpose(loc, (0, 1, 3, 2))
            vel = np.transpose(vel, (0, 1, 3, 2))
            assert (loc.shape[-2:] == (self.n_balls, 3) and vel.shape[-2:] == (self.n_balls, 3)), "Shape mismatch!"

        # edges = np.load(self.data_dir / f'edges_{self.suffix}.npy')
        charges = np.load(self.data_dir / f'charges_{self.suffix}.npy')
        mat_charges = charges.repeat(charges.shape[1], axis=2)
        edges = np.einsum('tij,tji ->tij', mat_charges, mat_charges)
        print(f"Loaded dataset {self.suffix} with {loc.shape[0]} samples, {loc.shape[2]} nodes, {loc.shape[3]} features")
        
        loc, vel, edge_attr, edges, charges = self.preprocess(loc, vel, edges, charges)
        return (loc, vel, edge_attr, charges), edges

    def preprocess(self, loc, vel, edges, charges):
        # cast to torch and swap n_nodes <--> n_features dimensions
        loc, vel = torch.tensor(loc).float(), torch.tensor(vel).float()
        n_nodes = loc.size(2)
        loc = loc[0:self.max_samples, :, :, :]  # limit number of samples
        vel = vel[0:self.max_samples, :, :, :]  # speed when starting the trajectory
        charges = charges[0:self.max_samples]
        edge_attr = []

        # Initialize edges and edge_attributes
        rows, cols = [], []
        for i in range(n_nodes):
            for j in range(n_nodes):
                if i != j:
                    edge_attr.append(edges[:, i, j])
                    rows.append(i)
                    cols.append(j)
        edges = [rows, cols]
        edge_attr = torch.tensor(np.array(edge_attr)).float().transpose(0, 1).unsqueeze(2) 
        # swap n_nodes <--> batch_size and add nf dimension
        return loc, vel, edge_attr, edges, torch.tensor(charges).float()

    def set_max_samples(self, max_samples):
        self.max_samples = int(max_samples)
        self.data, self.edges = self.load()

    def get_n_nodes(self):
        return self.data[0].size(1)

    def __getitem__(self, i):
        loc, vel, edge_attr, charges = self.data
        loc, vel, edge_attr, charges = loc[i], vel[i], edge_attr[i], charges[i]

        if self.dataset_name == "nbody":
            frame_0, frame_T = 6, 8
        elif self.dataset_name == "nbody_small":
            frame_0, frame_T = 30, 40
        elif self.dataset_name == "nbody_small_out_dist":
            frame_0, frame_T = 20, 30
        else:
            raise Exception("Wrong dataset partition %s" % self.dataset_name)

        return loc[frame_0], vel[frame_0], edge_attr, charges, loc[frame_T]

    def __len__(self):
        return len(self.data[0])

    def get_edges(self, batch_size, n_nodes):
        edges = [torch.LongTensor(self.edges[0]), torch.LongTensor(self.edges[1])]
        if batch_size == 1:
            return edges
        elif batch_size > 1:
            rows, cols = [], []
            for i in range(batch_size):
                rows.append(edges[0] + n_nodes * i)
                cols.append(edges[1] + n_nodes * i)
            edges = [torch.cat(rows), torch.cat(cols)]
        return edges


class NBodyDynamicsDataset(NBodyDataset):
    def __init__(self, partition='train', data_dir='.', max_samples=1e8, dataset="charged",dataset_name="nbody_small", n_balls=5, num_timesteps=10, num_inputs=1, rollout=False, traj_len=1,varDT=False):
        self.num_timesteps = num_timesteps
        self.rollout = rollout
        self.traj_len = traj_len
        self.num_inputs = num_inputs
        self.var_dt = varDT
        super(NBodyDynamicsDataset, self).__init__(data_dir, partition, max_samples, dataset, dataset_name, n_balls=n_balls)

    def __getitem__(self, i):
        loc, vel, edge_attr, charges = self.data
        loc, vel, edge_attr, charges = loc[i], vel[i], edge_attr[i], charges[i]

        if self.dataset_name == "nbody":
            frame_0, frame_T = 6, 8
        elif self.dataset_name == "nbody_small":
            frame_0, frame_T = 30, 40
        elif self.dataset_name == "nbody_small_out_dist":
            frame_0, frame_T = 20, 30
        else:
            raise Exception("Wrong dataset partition %s" % self.dataset_name)
        
        frame_T = frame_0 + self.num_timesteps
        
        if self.rollout:
                
            # if self.var_dt:
            #     #return all locs so that after its possible to select different delta T across the trajectory
            #     return loc[frame_0], vel[frame_0], edge_attr, charges, loc 
            
            delta_frame = frame_T - frame_0
            for i in range(self.traj_len):
                last = False
                #location
                if last:
                    locs = [loc[frame_0 + delta_frame + ii - self.num_timesteps] for ii in range(1, self.num_timesteps + 1)]
                else:
                    locs = [loc[frame_0 + delta_frame * ii // self.num_timesteps] for ii in range(1, self.num_timesteps + 1)]
                
                locs = np.stack(locs, axis=1) 
                
                if i == 0: # first iter
                    locs_m = locs
                else:
                    locs_m = np.concatenate((locs_m,locs),axis=1)
                #velocity
                if last:
                    vels = [vel[frame_0 + delta_frame + ii - self.num_timesteps] for ii in range(1, self.num_timesteps + 1)]
                else:
                    vels = [vel[frame_0 + delta_frame * ii // self.num_timesteps] for ii in range(1, self.num_timesteps + 1)]
                vels = np.stack(vels, axis=1)
                if i == 0: # first iter
                    vels_m = vels
                else:
                    vels_m = np.concatenate((vels_m,vels),axis=1)

                frame_0 += self.num_timesteps
                
            frame_0 = 30
            locs = locs_m
            

        else:
            delta_frame = frame_T - frame_0
            last = False
            if last:
                locs = [loc[frame_0 + delta_frame + ii - self.num_timesteps] for ii in range(1, self.num_timesteps + 1)]
            else:
                locs = [loc[frame_0 + delta_frame * ii // self.num_timesteps] for ii in range(1, self.num_timesteps + 1)]
            locs = np.stack(locs, axis=1)
            if last:
                vels = [vel[frame_0 + delta_frame + ii - self.num_timesteps] for ii in range(1, self.num_timesteps + 1)]
            else:
                vels = [vel[frame_0 + delta_frame * ii // self.num_timesteps] for ii in range(1, self.num_timesteps + 1)]
            vels = np.stack(vels, axis=1)

        if self.var_dt and self.num_inputs>1:
                
            assert self.num_inputs <= self.num_timesteps
            # idxs = torch.linspace(0, self.num_timesteps - 1, self.num_inputs, dtype=int)
            # loc_inputs = loc[frame_0 + idxs]
            # vel_inputs = vel[frame_0 + idxs]
            
            return loc, vel, edge_attr, charges, locs
        
        elif self.num_inputs > 1:
            assert self.num_inputs <= self.num_timesteps
            idxs = torch.linspace(0, self.num_timesteps - 1, self.num_inputs, dtype=int)
            loc_inputs = loc[frame_0 + idxs]
            vel_inputs = vel[frame_0 + idxs]
            # TODO: cosa fanno edge_attr?
            return loc_inputs, vel_inputs, edge_attr, charges, locs

        
        return loc[frame_0], vel[frame_0], edge_attr, charges, locs


if __name__ == "__main__":
    dataset = NBodyDynamicsDataset('train', data_dir='./dataset', max_samples=3000, num_timesteps=100)
    for i in dataset[100]:
        print(i.shape)
        print(i)

