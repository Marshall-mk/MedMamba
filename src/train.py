import os
import sys
import json
import torch
import torch.nn as nn
from torchvision import transforms, datasets
import torch.optim as optim
from tqdm import tqdm
import hydra  # for configurations
from omegaconf.omegaconf import OmegaConf  # config
from MedMamba import VSSM as medmamba

@hydra.main(config_path="../configs", config_name="configs", version_base="1.2")
def main(cfg):
    OmegaConf.to_yaml(cfg, resolve=True)
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print("using {} device.".format(device))

    data_transform = {
        "train": transforms.Compose(
            [
                transforms.RandomResizedCrop(cfg.model.image_size),
                transforms.RandomHorizontalFlip(),
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
            ]
        ),
        "val": transforms.Compose(
            [
                transforms.Resize((cfg.model.image_size, cfg.model.image_size)),
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
            ]
        ),
    }

    train_dataset = datasets.ImageFolder(
        root=cfg.model.train_data_path, transform=data_transform["train"]
    )
    train_num = len(train_dataset)

    flower_list = train_dataset.class_to_idx
    cla_dict = dict((val, key) for key, val in flower_list.items())
    # write dict into json file
    json_str = json.dumps(cla_dict, indent=4)
    with open(f"{cfg.model.history_path}class_indices.json", "w") as json_file:
        json_file.write(json_str)

    batch_size = cfg.train.batch_size
    nw = min(
        [os.cpu_count(), batch_size if batch_size > 1 else 0, 8]
    )  # number of workers
    print("Using {} dataloader workers every process".format(nw))

    train_loader = torch.utils.data.DataLoader(
        train_dataset, batch_size=batch_size, shuffle=True, num_workers=nw
    )

    validate_dataset = datasets.ImageFolder(
        root=cfg.model.val_data_path, transform=data_transform["val"]
    )
    val_num = len(validate_dataset)
    validate_loader = torch.utils.data.DataLoader(
        validate_dataset, batch_size=batch_size, shuffle=False, num_workers=nw
    )
    print(
        "using {} images for training, {} images for validation.".format(
            train_num, val_num
        )
    )

    net = medmamba(num_classes=cfg.model.classes)
    net.to(device)
    loss_function = nn.CrossEntropyLoss()
    optimizer = optim.Adam(net.parameters(), lr=0.0001)

    epochs = cfg.train.epochs
    best_acc = 0.0
    save_path =  f"{cfg.model.ckpt_path}{cfg.model.model_name}Net.pth"
    train_steps = len(train_loader)
    for epoch in range(epochs):
        # train
        net.train()
        running_loss = 0.0
        train_bar = tqdm(train_loader, file=sys.stdout)
        for step, data in enumerate(train_bar):
            images, labels = data
            optimizer.zero_grad()
            outputs = net(images.to(device))
            loss = loss_function(outputs, labels.to(device))
            loss.backward()
            optimizer.step()

            # print statistics
            running_loss += loss.item()

            train_bar.desc = "train epoch[{}/{}] loss:{:.3f}".format(
                epoch + 1, epochs, loss
            )

        # validate
        net.eval()
        acc = 0.0  # accumulate accurate number / epoch
        with torch.no_grad():
            val_bar = tqdm(validate_loader, file=sys.stdout)
            for val_data in val_bar:
                val_images, val_labels = val_data
                outputs = net(val_images.to(device))
                predict_y = torch.max(outputs, dim=1)[1]
                acc += torch.eq(predict_y, val_labels.to(device)).sum().item()

        val_accurate = acc / val_num
        print(
            "[epoch %d] train_loss: %.3f  val_accuracy: %.3f"
            % (epoch + 1, running_loss / train_steps, val_accurate)
        )
        # save training metrics
        with open(f"{cfg.model.history_path}train_metrics.txt", "a") as f:
            f.write(
                f"epoch: {epoch + 1}, train_loss: {running_loss / train_steps}, val_accuracy: {val_accurate}\n"
            )
        if val_accurate > best_acc:
            best_acc = val_accurate
            torch.save(net.state_dict(), save_path)
            print("model saved")

    print("Finished Training")


if __name__ == "__main__":
    main()
