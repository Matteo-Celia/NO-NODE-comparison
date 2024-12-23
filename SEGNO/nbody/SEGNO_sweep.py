import wandb

from train_nbody_one_test import train as train_model
from sweep_params import param_dicts

MAX_RUN = 50

#WANDB key for login: d8446caf4ba3380287984852fefa3ca3557b664d

wandb.login()


sweep_config = {
    'method': 'grid',  # or 'random'
    'metric': {
        'name': 'loss',
        'goal': 'minimize'
    },
    'parameters': param_dicts
}



def train(config=None):
    
    # Set up W&B config for the sweep
    with wandb.init(config=config):
    # Access the hyperparameters through wandb.config
        
        config = wandb.config

       

        # if config.gpus == 0:
        #     config.mode = 'cpu'
        #     train_model(0, config)
        
        # elif config.gpus == 1:
        #     config.mode = 'gpu'
        #     train_model(0, config)
        train_model(0, config)
        

sweep_id = wandb.sweep(sweep_config, project="SEGNO-sweep-new")
wandb.agent(sweep_id, train) #MAX_RUN