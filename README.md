# Grainfather.py

## A tool for syncing brew recipes from "Kleiner Brauhelfer" to the Grainfather brew community database

### Introduction

[Grainfather][1] is the name of a series of home brewing equipment
produced by the New Zealand company Bevie and sold to customers all
over the world. With relatively affordable as well as high quality
products many home brewers love their shiny stainless steel
Grainfather equipment. :-) Brew recipes can be managed on the
[Grainfather community web site][2] and kept snychronized with iOS and
Android apps on smartphones and tablet computers. While this recipe
management is not necessarily limited to Grainfather brewing hardware,
a specific benefit of such a combination is that the app can easily
control the brewing process through a Bluetooth connection, from water
heating, over precise mash step profiles, up to the boil with various
boil addition alarms.

The [Kleiner Brauhelfer][3] (KBH) is an open source software for brew
recipe development and management. It is widely used among home
brewers primarily in Germany for many years. Therefore many brewers
have lots of recipes and according brew session data stored in their
"KBH" database. Many of them do not want to use another management
software, when they recently replaced their brewing equipment by a
Grainfather.

The aim of this project is to transfer and synchronize recipes from a
personal KBH database to the Grainfather site.

### License

See [LICENSE.txt][4]

### Prerequisites

This software is being developed and used on current Linux systems as
of 2018. It is implemented in Python 3.x. You will need the "requests"
package[5], e.g. the Debian package "python3-requests" on Ubuntu or
Debian systems.

Of course you need KBH. The system running this software just has to
have access to the SQLite3 database file of KBH. E.g., I run KBH on a
Mac and keep the database stored on my Nextcloud server. That
Nextcloud file is also shared by my Linux host, on which I run this
software.

Of course you also need an account on the Grainfather community site.
When running this software your will have to supply your Grainfather
community account credentials. If you already have an account, you
probably want to create a new one, just to make sure this software
will not overwrite or mix up any data on your primary account.

### Status

This project is at a very early stage and it is unclear how far I will
push it. Feel free to try it out. Feedback and contributions are
welcome. But please do not expect things to work without any problems.

### Usage Example

```
$ ./Grainfather.py -h
Usage: ./Grainfather.py [options] [command [argument] ]
  -v           --verbose             increase the logging level
  -d           --debug               run at maximum debug level
  -n           --dryrun              do not write any data
  -f           --force               force operations
  -h           --help                this help message
  -u username  --user username       Grainfather community username
  -p password  --password password   Grainfather community password
  -P file      --pwfile file         read password from file
  -k file      --kbhfile file        Kleiner Brauhelfer database file
Commands:
  list                               list user's recipes
  dump ["namepattern"]               dump user's recipes 
  push ["namepattern"]               push recipes from KBH to GF
  delete "namepattern"               delete user's recipes

$ ./Grainfather.py -u f-grainfather@familie-steinberg.org -P ~/.grainfather.passwd -k ~/.kleiner-brauhelfer/kb_daten.sqlite push "#004 Altbier"
INFO:session:GET https://oauth.grainfather.com/customer/account/login/ -> 200
INFO:session:POST https://oauth.grainfather.com/customer/account/loginPost/ -> 200
INFO:session:GET https://brew.grainfather.com -> 200
INFO:session:GET https://brew.grainfather.com/my-recipes/data?page=1 -> 200
INFO:session:GET https://brew.grainfather.com/my-recipes/data?page=2 -> 200
INFO:interpreter:Updating <current Recipe id 181607 named "#004 Altbier">
INFO:session:PUT https://brew.grainfather.com/recipes/181607 -> 200
INFO:session:GET https://brew.grainfather.com/logout -> 200
```

### TODO

- beatify list output format (sort, more columns)
- configuration file (user id, password file, kbh file)
- implement recipe["fermentation_steps"]
- document KBH [[]]-tags
- more operations: rename? ...others?
- allow a separator to suppress parts of KBH comments
- daemon mode, listening for database updates in the background
- persistent sessions for faster subsequent commands -> new command "logout"
- implement more KBH [[]]-tags (e.g. malt-ppg)
- local log file of write operations
- maybe, a "restore" command would be possible?
- better error handling

- split: Python API / command line tool
- handle ratings somehow?
- (partial) sync back from GF to KBH?


[1]: https://grainfather.com
[2]: https://brew.grainfather.com
[3]: https://github.com/Gremmel/kleiner-brauhelfer
[4]: LICENSE.txt
[5]: http://docs.python-requests.org/en/master/user/install/


