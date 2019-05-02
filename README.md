# sushi-chef-folkdc
Sushi Chef script for importing folkdc content

## Installation

* Install [Python 3](https://www.python.org/downloads/) if you don't have it already.

* Install [pip](https://pypi.python.org/pypi/pip) if you don't have it already.

* Create a Python virtual environment for this project (optional, but recommended):
   * Install the virtualenv package: `pip install virtualenv`
   * The next steps depends if you're using UNIX (Mac/Linux) or Windows:
      * For UNIX systems:
         * Create a virtual env called `venv` in the current directory using the
           following command: `virtualenv -p python3  venv`
         * Activate the virtualenv called `venv` by running: `source venv/bin/activate`.
           Your command prompt will change to indicate you're working inside `venv`.
      * For Windows systems:
         * Create a virtual env called `venv` in the current directory using the
           following command: `virtualenv -p C:/Python36/python.exe venv`.
           You may need to adjust the `-p` argument depending on where your version
           of Python is located.
         * Activate the virtualenv called `venv` by running: `.\venv\Scripts\activate`

* Run `pip install -r requirements.txt` to install the required python libraries.



## Usage

     ./sushichef.py -v --reset --token=".token" --lang=es
     ./sushichef.py -v --reset --token=".token" --lang=en
     ./sushichef.py -v --reset --token=".token" --lang=fi
     ./sushichef.py -v --reset --token=".token" --lang=it
     ./sushichef.py -v --reset --token=".token" --lang=de
     ./sushichef.py -v --reset --token=".token" --lang=ro
     ./sushichef.py -v --reset --token=".token" --lang=tr
