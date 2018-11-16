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
and "dateutil" packages, e.g. the Debian packages "python3-requests"
and "python3-dateutil" on Ubuntu or Debian systems.

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

### Special Attributes

Some pieces of information, that might be useful to get displayes on
the Grainfather recipe site, do not have a representation in KBH.
Therefore, one might add some information in a special syntax to the
KBH recipe comment field. The general syntax is "[[TAGNAME: VALUE]]":

*"Image"*: May contain a URL of a Photo, e.g.:

```
[[Image: https://frankensteiner.familie-steinberg.org/wp-content/uploads/2018/03/00083E8B-4A5A-4696-B54A-EB9357A23F13.jpeg]]
```

*"BJCP-Style"*: May contain the short ID of a BJCP 2015 beer style, e.g.:

```
[[BJCP-Style: 18B]]
```

*"Public"*: May contain "True" to flag a recipe to be public, default is false, e.g.:

```
[[Public: True]]
```

*"Fermentation"*: May contain a comma seprated list of fermentation
steps each of the form "NAME:DAYS@TEMP". if the value starts with a
comma, this list is appended to the intrinsic first fermentation steps
built from the KBH "Gärverlauf" or other data from the "Brau- &
Gärdaten" tab. E.g.:

```
[[Fermentation: ,Flaschengärung:14@22]]
```

### Status

This project is at a very early stage and it is unclear how far I will
push it. However, for me it does its job quite well already. Feel free
to try it out, but please do not expect things to work without any
problems. Feedback and contributions are welcome, preferably on the
GitHub site at https://github.com/frsteinb/Grainfather as issues or
pull requests.

### Usage Example

```
$ ./Grainfather.py -h
Usage: ./Grainfather.py [options] [command [argument] ]
  -v           --verbose             increase the logging level
  -d           --debug               run at maximum debug level
  -n           --dryrun              do not write any data
  -f           --force               force operations
  -h           --help                this help message
  -c file      --config file         read configuration file
  -u username  --user username       Grainfather community username
  -p password  --password password   Grainfather community password
  -P file      --pwfile file         read password from file
  -l           --logout              logout (instead of keeping session persistent)
  -k file      --kbhfile file        Kleiner Brauhelfer database file
Commands:
  list ["namepattern"]               list user's recipes
  dump ["namepattern"]               dump user's recipe(s) 
  push ["namepattern"]               push recipe(s) from KBH to GF
  delete "namepattern"               delete user's recipe(s)
  diff "namepattern"                 show json diff between kbh and gf version of a recipe
  daemon                             run as daemon keeping GF synced with KBH
  logout                             logout and invalidate persistent session

$ cat ~/.grainfather.config 
{
    "username": "f-grainfather@familie-steinberg.org",
    "passwordFile": "~/.grainfather.password",
    "kbhFile": "~/.kleiner-brauhelfer/kb_daten.sqlite"
}

$ ./Grainfather.py -v list "#01*"
INFO:session:GET https://oauth.grainfather.com/customer/account/login/ -> 200
INFO:session:POST https://oauth.grainfather.com/customer/account/loginPost/ -> 302
INFO:session:GET https://brew.grainfather.com -> 302
INFO:session:GET https://brew.grainfather.com -> 200
INFO:session:Saved session state to ~/.grainfather.state
INFO:session:GET https://brew.grainfather.com/my-recipes/data?page=1 -> 200
INFO:session:GET https://brew.grainfather.com/my-recipes/data?page=2 -> 200
  181572 kg-- 2018-11-09 18:40 2018-11-11 09:30   22.0l #010 Spontaneous IPA
  181571 kgp- 2018-11-09 18:42 2018-11-11 09:30   18.8l #011 Black Russian Imperial Stout
  181573 kgp- 2018-11-09 18:42 2018-11-10 11:02   19.2l #012 Simply Red Ale
  181639 kgp- 2018-11-09 18:44 2018-11-11 09:30   20.2l #013 Pumpkin Ale
  181574 kgpo 2018-11-13 14:15 2018-11-13 08:47   23.8l #014 PIPA

$ ./Grainfather.py -v push
INFO:session:Read session state from ~/.grainfather.state
INFO:session:GET https://brew.grainfather.com/my-recipes/data?page=1 -> 200
INFO:session:GET https://brew.grainfather.com/my-recipes/data?page=2 -> 200
INFO:interpreter:<current Recipe id 181640 named "#000 Beispielsud"> needs no update
INFO:interpreter:<current Recipe id 181902 named "#001 Big Bang Pale Ale"> needs no update
INFO:interpreter:<current Recipe id 181605 named "#002 Black Hole Sun Extra Stout"> needs no update
INFO:interpreter:<current Recipe id 181606 named "#003 Hoppel-Di-Hop Oster-Ale"> needs no update
INFO:interpreter:<current Recipe id 181607 named "#004 Altbier"> needs no update
INFO:interpreter:<current Recipe id 181608 named "#005 Citra Weizenbier"> needs no update
INFO:interpreter:<current Recipe id 181609 named "#006 Mate-Eistee"> needs no update
INFO:interpreter:<current Recipe id 181610 named "#007 Summer In The City Pale Ale"> needs no update
INFO:interpreter:<current Recipe id 181611 named "#008 Level 42 Brown Ale"> needs no update
INFO:interpreter:<current Recipe id 181612 named "#009 Frankator Weizendoppelbock"> needs no update
INFO:interpreter:<current Recipe id 181571 named "#011 Black Russian Imperial Stout"> needs no update
INFO:interpreter:<current Recipe id 181572 named "#010 Spontaneous IPA"> needs no update
INFO:interpreter:<current Recipe id 181639 named "#013 Pumpkin Ale"> needs no update
INFO:interpreter:<current Recipe id 181573 named "#012 Simply Red Ale"> needs no update
INFO:interpreter:Updating <current Recipe id 181574 named "#014 PIPA">
INFO:session:PUT https://brew.grainfather.com/recipes/181574 -> 200
```

### TODO

- allow a separator to suppress parts of KBH comments
- implement more KBH [[]]-tags (e.g. malt-ppg)
- maybe, a "restore" command would be possible?
- improved error handling
- split: Python API / command line tool
- handle ratings somehow?
- (partial) sync back from GF to KBH?


[1]: https://grainfather.com
[2]: https://brew.grainfather.com
[3]: https://github.com/Gremmel/kleiner-brauhelfer
[4]: LICENSE.txt
[5]: http://docs.python-requests.org/en/master/user/install/


