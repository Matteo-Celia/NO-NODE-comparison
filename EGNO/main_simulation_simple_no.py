import argparse
from argparse import Namespace
import torch
import torch.utils.data
from simulation.dataset_simple import NBodyDynamicsDataset as SimulationDataset
from model.egno import EGNO
from utils import EarlyStopping
import os
from torch import nn, optim
import json

import random
import numpy as np
import wandb

parser = argparse.ArgumentParser(description='EGNO')
parser.add_argument('--exp_name', type=str, default='exp_1', metavar='N', help='experiment_name')
parser.add_argument('--batch_size', type=int, default=100, metavar='N',
                    help='input batch size for training (default: 128)')
parser.add_argument('--epochs', type=int, default=1000, metavar='N',
                    help='number of epochs to train (default: 10)')
parser.add_argument('--no-cuda', action='store_true', default=False,
                    help='enables CUDA training')
parser.add_argument('--seed', type=int, default=1, metavar='S',
                    help='random seed (default: 1)')
parser.add_argument('--log_interval', type=int, default=1, metavar='N',
                    help='how many batches to wait before logging training status')
parser.add_argument('--test_interval', type=int, default=5, metavar='N',
                    help='how many epochs to wait before logging test')
parser.add_argument('--outf', type=str, default='exp_results', metavar='N',
                    help='folder to output the json log file')
parser.add_argument('--lr', type=float, default=5e-4, metavar='N',
                    help='learning rate')
parser.add_argument('--nf', type=int, default=64, metavar='N',
                    help='hidden dim')
parser.add_argument('--model', type=str, default='egno', metavar='N')
parser.add_argument('--n_layers', type=int, default=4, metavar='N',
                    help='number of layers for the autoencoder')
parser.add_argument('--max_training_samples', type=int, default=3000, metavar='N',
                    help='maximum amount of training samples')
parser.add_argument('--weight_decay', type=float, default=1e-12, metavar='N',
                    help='timing experiment')
parser.add_argument('--data_dir', type=str, default='',
                    help='Data directory.')
parser.add_argument('--dropout', type=float, default=0.5,
                    help='Dropout rate (1 - keep probability).')
parser.add_argument("--config_by_file", default=None, nargs="?", const='', type=str, )

parser.add_argument('--lambda_link', type=float, default=1,
                    help='The weight of the linkage loss.')
parser.add_argument('--n_cluster', type=int, default=3,
                    help='The number of clusters.')
parser.add_argument('--flat', action='store_true', default=False,
                    help='flat MLP')
parser.add_argument('--interaction_layer', type=int, default=3,
                    help='The number of interaction layers per block.')
parser.add_argument('--pooling_layer', type=int, default=3,
                    help='The number of pooling layers in EGPN.')
parser.add_argument('--decoder_layer', type=int, default=1,
                    help='The number of decoder layers.')
parser.add_argument('--norm', action='store_true', default=False,
                    help='Use norm in EGNO')

parser.add_argument('--num_inputs', type=int, default=1,
                    help='The number of inputs to give for each prediction step.')
parser.add_argument('--num_timesteps', type=int, default=10,
                    help='The number of time steps.')
parser.add_argument('--time_emb_dim', type=int, default=32,
                    help='The dimension of time embedding.')
parser.add_argument('--num_modes', type=int, default=2,
                    help='The number of modes.')

time_exp_dic = {'time': 0, 'counter': 0}


args = parser.parse_args()
if args.config_by_file is not None:
    if len(args.config_by_file) == 0:
        job_param_path = './configs/config_simulation_simple_no.json'
    else:
        job_param_path = args.config_by_file
    with open(job_param_path, 'r') as f:
        hyper_params = json.load(f)
        # Only update existing keys
        args = vars(args)
        args.update((k, v) for k, v in hyper_params.items() if k in args)
        args = Namespace(**args)

args.cuda = not args.no_cuda and torch.cuda.is_available()

wandb.login()

wandb.init( project="EGNO-NO-NODE-comparison")# set the wandb project where this run will be logged


device = torch.device("cuda" if args.cuda else "cpu")
loss_mse = nn.MSELoss(reduction='none')

print(args)
try:
    os.makedirs(args.outf)
except OSError:
    pass

try:
    os.makedirs(args.outf + "/" + args.exp_name)
except OSError:
    pass


def main():
    # fix seed
    seed = args.seed
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)

    dataset_train = SimulationDataset(partition='train', max_samples=args.max_training_samples,
                                      data_dir=args.data_dir, num_timesteps=args.num_timesteps, num_inputs=args.num_inputs)
    loader_train = torch.utils.data.DataLoader(dataset_train, batch_size=args.batch_size, shuffle=True, drop_last=True,
                                               num_workers=0)

    dataset_val = SimulationDataset(partition='val',
                                    data_dir=args.data_dir, num_timesteps=args.num_timesteps, num_inputs=args.num_inputs)
    loader_val = torch.utils.data.DataLoader(dataset_val, batch_size=args.batch_size, shuffle=False, drop_last=False,
                                             num_workers=0)

    dataset_test = SimulationDataset(partition='test',
                                     data_dir=args.data_dir, num_timesteps=args.num_timesteps, num_inputs=args.num_inputs, rollout=True, traj_len=10)
    loader_test = torch.utils.data.DataLoader(dataset_test, batch_size=args.batch_size, shuffle=False, drop_last=False,
                                              num_workers=0)

    if args.model == 'egno':
        model = EGNO(n_layers=args.n_layers, in_node_nf=1, in_edge_nf=2, hidden_nf=args.nf, device=device,
                     with_v=True, flat=args.flat, activation=nn.SiLU(), norm=args.norm, use_time_conv=True,
                     num_modes=args.num_modes, num_timesteps=args.num_timesteps, time_emb_dim=args.time_emb_dim, num_inputs=args.num_inputs)
    else:
        raise NotImplementedError('Unknown model:', args.model)

    print(model)
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    model_save_path = args.outf + '/' + args.exp_name + '/' + 'saved_model.pth'
    print(f'Model saved to {model_save_path}')
    early_stopping = EarlyStopping(patience=50, verbose=True, path=model_save_path)

    results = {'eval epoch': [], 'val loss': [], 'test loss': [], 'train loss': []}
    best_val_loss = 1e8
    best_test_loss = 1e8
    best_epoch = 0
    best_train_loss = 1e8
    for epoch in range(0, args.epochs):
        train_loss = train(model, optimizer, epoch, loader_train,args)
        results['train loss'].append(train_loss)
        if epoch % args.test_interval == 0:
            val_loss = train(model, optimizer, epoch, loader_val,args, backprop=False)
            test_loss, avg_num_steps = train(model, optimizer, epoch, loader_test,args, backprop=False, rollout=True)

            results['eval epoch'].append(epoch)
            results['val loss'].append(val_loss)
            results['test loss'].append(test_loss)
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_test_loss = test_loss
                best_train_loss = train_loss
                best_avg_num_steps = avg_num_steps
                best_epoch = epoch
                # Save model is move to early stopping.
            print("*** Best Val Loss: %.5f \t Best Test Loss: %.5f \t Best Test avg num steps: %.4f \t Best epoch %d"
                  % (best_val_loss, best_test_loss, best_avg_num_steps, best_epoch))
            early_stopping(val_loss, model)
            if early_stopping.early_stop:
                print("Early Stopping.")
                break

        json_object = json.dumps(results, indent=4)
        with open(args.outf + "/" + args.exp_name + "/loss.json", "w") as outfile:
            outfile.write(json_object)

        
    return best_train_loss, best_val_loss, best_test_loss, best_epoch


def train(model, optimizer, epoch, loader, args, backprop=True, rollout=False):
    if backprop:
        model.train()
    else:
        model.eval()

    res = {'epoch': epoch, 'loss': 0,"tot_num_steps": 0,"avg_num_steps": 0, 'counter': 0, 'lp_loss': 0}
    preds = []
    #print(f"this is the {loader.dataset.partition} partition")
    
    for batch_idx, data in enumerate(loader):
        data = [d.to(device) for d in data]
        loc, vel, edge_attr, charges, loc_true = data
        
        n_nodes = 5
        
    
        optimizer.zero_grad()

        if args.model == 'egno':

            if args.num_inputs > 1:
                loc_inputs = []
                vel_inputs = []
                loc_mean = []
                for i in range(args.num_inputs):
                    loc_inputs.append(loc[i].view(-1, loc[i].shape[-1]))
                    loc_mean.append(loc[i].mean(dim=1, keepdim=True).repeat(1, n_nodes, 1).view(-1, loc[i].size(2)))
                    vel_inputs.append(vel[i].view(-1, vel.shape[-1]))
                    
                batch_size = loc[0].shape[0] // n_nodes
                edges = loader.dataset.get_edges(batch_size, n_nodes)
                edges = [edges[0].to(device), edges[1].to(device)]

                rows, cols = edges

                #do the same for nodes, loc dist edge attr (inside egno some are not needed to be repeated on more steps because are the same)
            else:
            
                loc_mean = loc.mean(dim=1, keepdim=True).repeat(1, n_nodes, 1).view(-1, loc.size(2))  # [BN, 3]

                loc = loc.view(-1, loc.shape[-1])
                vel = vel.view(-1, vel.shape[-1])
                
                batch_size = loc.shape[0] // n_nodes
                nodes = torch.sqrt(torch.sum(vel ** 2, dim=1)).unsqueeze(1).detach()
                edges = loader.dataset.get_edges(batch_size, n_nodes)
                edges = [edges[0].to(device), edges[1].to(device)]

                rows, cols = edges
                loc_dist = torch.sum((loc[rows] - loc[cols])**2, 1).unsqueeze(1)  # relative distances among locations
                edge_attr_o = edge_attr.view(-1, edge_attr.shape[-1])
                edge_attr = torch.cat([edge_attr_o, loc_dist], 1).detach()  # concatenate all edge properties
            
            
            if rollout:
                traj_len = 10
                
                locs_true = loc_true.view(batch_size * n_nodes, args.num_timesteps*traj_len, 3).transpose(0, 1)
                #print(locs_true.shape)
                locs_pred = rollout_fn(model, nodes, loc, edges, vel, edge_attr_o, edge_attr,loc_mean, n_nodes, traj_len).to(device)
                
                corr, avg_num_steps, first_invalid_idx = pearson_correlation_batch(locs_pred, locs_true, n_nodes) #locs_pred[::10]
                print(first_invalid_idx)
                locs_pred = locs_pred[:20]
                locs_true = locs_true[:20]
                #print(torch.isnan(locs_pred).any(), torch.isinf(locs_pred).any())
                #locs_true = locs_true.transpose(0, 1).contiguous().view(-1, 3)
                #locs_pred = locs_pred.transpose(0, 1).contiguous().view(-1, 3)
                
                res["tot_num_steps"] += avg_num_steps*batch_size
                
                #loss with metric (A-MSE)
                losses = loss_mse(locs_pred, locs_true).view(20, batch_size * n_nodes, 3) #args.num_timesteps*traj_len
                #print(losses.shape)
                #print(torch.max(losses))
                #print(torch.isnan(losses).any(), torch.isinf(losses).any())
                losses = torch.mean(losses, dim=(1, 2))
                #print(losses,torch.max(losses))
                
                #print(torch.isnan(losses).any(), torch.isinf(losses).any())
                loss = torch.mean(losses) 
                
            else:
                loc_end = loc_true.view(batch_size * n_nodes, args.num_timesteps, 3).transpose(0, 1).contiguous().view(-1, 3)
                loc_pred, vel_pred, _ = model(loc, nodes, edges, edge_attr, v=vel, loc_mean=loc_mean)
                #pearson_correlation_batch(loc_pred.reshape(args.num_timesteps,batch_size * n_nodes, 3),loc_end,n_nodes)
                losses = loss_mse(loc_pred, loc_end).view(args.num_timesteps, batch_size * n_nodes, 3)
                losses = torch.mean(losses, dim=(1, 2))
                loss = torch.mean(losses)
                
        else:
            raise Exception("Wrong model")
        

        if backprop:
            loss.backward()
            optimizer.step()
        if rollout:
            res['loss'] += loss.item() * batch_size
        else:
            res['loss'] += losses[-1].item() * batch_size
        res['counter'] += batch_size
        res["avg_num_steps"] = res["tot_num_steps"] / res["counter"]
    if not backprop:
        prefix = "==> "
    else:
        prefix = ""
    print('%s epoch %d avg loss: %.5f avg lploss: %.5f'
          % (prefix+loader.dataset.partition, epoch, res['loss'] / res['counter'], res['lp_loss'] / res['counter']))
    
    avg_loss = res['loss'] / res['counter']
    wandb.log({f"{loader.dataset.partition}_loss": avg_loss, "epoch": epoch+1})

    if rollout:
        
        return res['loss'] / res['counter'], res['avg_num_steps']
    else:
        return res['loss'] / res['counter']


def rollout_fn(model, nodes, loc, edges, v, edge_attr_o, edge_attr, loc_mean, n_nodes, traj_len):
    num_steps=10
    loc_preds = torch.zeros((traj_len,loc.shape[0]*num_steps,loc.shape[-1]))
    vel = v
    for i in range(traj_len):
        #print("Inside loop \n")
        #print(loc.shape,loc)
        loc, vel, _ = model(loc.detach(), nodes, edges, edge_attr,v=vel.detach(), loc_mean=loc_mean)
        #print(torch.isnan(loc).any(), torch.isinf(loc).any())
        #print("loc")
        #print(loc.shape)
        # print(loc.shape)
        loc_preds[i] = loc
        #print(torch.sum(loc[-1]))
        loc = loc.view(num_steps,-1, loc.shape[-1])[-1]#.transpose(0,1)[-1] #get last element in the inner trajectory
        vel = vel.view(num_steps, -1, vel.shape[-1])[-1] #get last element in the inner trajectory
        #print(loc.shape)
        #print(torch.sum(loc))
        #exit()
        # print("loc \t")
        # print(torch.isnan(loc).any(), torch.isinf(loc).any())
        # print("vel \t")
        # print(torch.isnan(vel).any(), torch.isinf(vel).any())
        nodes = torch.sqrt(torch.sum(vel ** 2, dim=1)).unsqueeze(1).detach()
        rows, cols = edges
        loc_dist = torch.sum((loc[rows] - loc[cols])**2, 1).unsqueeze(1)  # relative distances among locations
        edge_attr = torch.cat([edge_attr_o, loc_dist], 1).detach()  # concatenate all edge properties
        loc = loc.view(-1, n_nodes, loc.shape[-1])
        loc_mean = loc.mean(dim=1, keepdim=True).repeat(1, n_nodes, 1).view(-1, loc.size(2))
        loc = loc.view(-1, loc.shape[-1])
        # print("loc \t")
        # print(torch.isnan(loc).any(), torch.isinf(loc).any())
        # print("nodes \t")
        # print(torch.isnan(nodes).any(), torch.isinf(nodes).any())
        # print("edge attr \t")
        # print(torch.isnan(edge_attr).any(), torch.isinf(edge_attr).any())
        # print("loc mean \t")
        # print(torch.isnan(loc_mean).any(), torch.isinf(loc_mean).any())
    
    # print("\n outside loop \n")
    # print(torch.isnan(loc_preds).any())
    
    loc_preds = loc_preds.reshape(traj_len*num_steps, -1, 3)
    
    return loc_preds

def pearson_correlation_batch(x, y, N):
    """
    Compute the Pearson correlation for each time step (T) in each batch (B).
    
    Args:
    - x: Tensor of shape (T, B*N, 3), predicted states.
    - y: Tensor of shape (T, B*N, 3), ground truth states.
    
    Returns:
    - correlations: Tensor of shape (B, T), Pearson correlation for each time step in each batch.
    """
    
    # Reshape to (B, T, N*3) 
    
    T = x.shape[0]
    B = x.size(1) // N
    x = x.reshape( T, B, -1)[:25].transpose(0,1)  # Flatten N and 3 into a single dimension
    y = y.reshape( T, B, -1)[:25].transpose(0,1)
    
    
    # Mean subtraction
    mean_x = x.mean(dim=2, keepdim=True)
    mean_y = y.mean(dim=2, keepdim=True)
    
    xm = x - mean_x
    ym = y - mean_y

    # Compute covariance between x and y along the flattened dimensions
    covariance = (xm * ym).sum(dim=2)

    # Compute standard deviations along the flattened dimensions
    std_x = torch.sqrt((xm ** 2).sum(dim=2))
    std_y = torch.sqrt((ym ** 2).sum(dim=2))

    # Compute Pearson correlation for each sample in the batch
    correlation = covariance / (std_x * std_y)

    #number of steps before reaching a value of correlation, between prediction and ground truth for each timesteps, lower than 0.5
    num_steps_batch = []

    for i in range(correlation.shape[0]):
        
        if any(correlation[i] < 0.5):
            num_steps_before = (correlation[i] < 0.5).nonzero(as_tuple=True)[0][0].item()
            
        else:
            num_steps_before = T
        num_steps_batch.append(num_steps_before)

    # Check if all values along B dimension are >= 0.5 for each T
    mask = torch.all(correlation >= 0.5, dim=0)

    # Convert the boolean mask to int for argmax
    first_failure_index = torch.argmax(~mask.int()).item()

    # If no failures, return the number of columns as the "end"
    if mask.all():
        first_failure_index = correlation.size(1)       
    print("first invalid")
    print(first_failure_index,torch.mean(torch.Tensor(num_steps_batch)))
    #exit()
    #return the average (in the batch) number of steps before reaching a value of correlation lower than 0.5
    #return the minimum first index along T dimension after which correlation drops below the threshold                                 
    return correlation, torch.mean(torch.Tensor(num_steps_batch)), first_failure_index 


    

if __name__ == "__main__":
    best_train_loss, best_val_loss, best_test_loss, best_epoch = main()
    print("best_train = %.6f" % best_train_loss)
    print("best_val = %.6f" % best_val_loss)
    print("best_test = %.6f" % best_test_loss)
    print("best_epoch = %d" % best_epoch)
    print("best_train = %.6f, best_val = %.6f, best_test = %.6f, best_epoch = %d"
          % (best_train_loss, best_val_loss, best_test_loss, best_epoch))

    wandb.finish()
