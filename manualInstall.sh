read -p "Is You USE docker? (y/n, (y)) : " isUseDocker

#.env
echo .env Setting
if [ ! -f ".env" ]; then
    sudo cp .env.example .env
    if [[ $isUseDocker == "n" ]]; then
        sudo sed -i "s/DB_HOST=mysql/#DB_HOST=mysql #<-- Use Docker\nDB_HOST=localhost/" .env
        sudo sed -i "s/REDIS_HOST=redis/#REDIS_HOST=redis #<-- Use Docker\nREDIS_HOST=localhost/" .env
    fi
    read -p "sudo vim .env"
    sudo vim .env
fi
if [ ! -f "logging.yaml" ]; then
    sudo cp logging.yaml.example logging.yaml
fi
export $(grep -v '^#' .env | xargs) #환경변수 가져옴

sudo apt update

#nginx
echo nginx install
if [ ! -d "../certs" ]; then
    sudo mkdir ../certs
    sudo wget -O ../certs/cert.crt https://aodd.xyz/wireguard/cert.crt
    sudo wget -O ../certs/cert.key https://aodd.xyz/wireguard/cert.key
fi
if ! dpkg -l | grep -q nginx; then
    sudo apt install -y nginx
fi
if [ ! -d "/etc/nginx/logs" ]; then
    sudo mkdir /etc/nginx/logs
fi
sudo sed -i "s/user www-data;/user $(whoami); #www-data;/" /etc/nginx/nginx.conf
sudo bash ./scripts/install-nginx-config.sh
sudo service nginx restart

#docker
echo docker install
bash get.docker.com
#sudo curl https://aodd.xyz/wireguard/get.docker.com | sh
sudo usermod -aG docker $(whoami)
sudo apt install -y make
sudo make build

#mysql
echo mysql install
if [[ $isUseDocker == "n" && ! $(dpkg -l | grep -q mysql) ]]; then
    sudo apt install -y mysql-server
    #sudo mysql_secure_installation
    sudo mysql -u root <<EOF
CREATE USER 'osu'@'%' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON *.* TO 'osu'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
CREATE DATABASE ${DB_NAME};
USE ${DB_NAME};
source migrations/base.sql
EOF
    sudo sed -i "s/bind-address/bind-address = *\n#bind-address/" /etc/mysql/mysql.conf.d/mysqld.cnf
    #read -p "sudo vim /etc/mysql/mysql.conf.d/mysqld.cnf"
    #sudo vim /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo service mysql restart
fi

#redis
echo redis install
if [[ $isUseDocker == "n" && ! $(dpkg -l | grep -q redis) ]]; then
    sudo apt install -y redis-server
    sudo sed -i "s/bind 127.0.0.1 -::1/#bind 127.0.0.1 -::1\nbind * -::*\nrequirepass ${REDIS_PASS}/" /etc/redis/redis.conf
    #read -p "sudo vim /etc/redis/redis.conf"
    #sudo vim /etc/redis/redis.conf
    sudo service redis restart
fi

#Rust & Cargo
echo "rust & cargo install"
sudo apt install -y build-essential
sudo curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env

#python3
echo python3-venv install
sudo apt install -y python3-venv
if [ ! -d "../venv" ]; then
    python3 -m venv ../venv
    sudo ln -r -s ../venv/bin/python ../venv/bin/py && sudo ln -r -s ../venv/bin/python ../venv/bin/chopy && sudo ln -r -s ../venv/bin/python ../venv/bin/guweb
    source ../venv/bin/activate
    pip install -r requirements-chopy+guweb.txt
fi

echo -e "\n\n\nexit 명령어로 터미널 재시작 하세요!"
read