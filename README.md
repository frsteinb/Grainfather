# Grainfather.py

## A tool for syncing brew recipes from "Kleiner Brauhelfer" to the Grainfather brew community database

### Introduction

The [Grainfather company][1] produces home brewing equipment and
sells it to customers all over the
world. With relatively affordable as well as high quality products
many home brewers love their shiny stainless steel Grainfather
equipment. :-) Brew recipes can be managed on the [Grainfather community
web site][2] and kept snychronized with iOS and Android apps on
smartphones and tablet computers. While this recipe management is not
necessarily limited to Grainfather brewing hardware, a specific
benefit of such a combination is that the app can easily control
the brewing process from water heating, over precise mash step profiles,
up to the boil with various boil addition alarms.

The [Kleiner Brauhelfer][3] (KBH) is an open source software for brew recipe
development and management. It is widely used among home brewers in
Germany for many years. Therefore many brewers have lots of recipes
and according brew session data stored in their "KBH" database. Many
of them do not want to use another management software, when they
recently replaced their brewing equipment by a Grainfather.

The aim of this project is to transfer and synchronize recipes
from a personal KBH database to the Grainfather site.

### License

See [LICENSE.txt][4]

### Prerequisites

This software is being developed and used on current Linux and MacOS
systems as of 2018. It is implemented in Python 3.x. Besides that
there should be no specific needs.

Of course you need KBH. The system running this software just has
to have access to the SQLite3 database file. E.g., I run KBH on
a Mac and keep the database stored on my Nextcloud server. That
Nextcloud file is also shared by my Linux host, on which I run
this software.

And of course you need an account on the Grainfather community site.
When running this software your will have to supply your Grainfather
account credentials. If you already have an account, you probably
want to create a new one, just to make sure this software will not
overwrite or delete any data on your primary account.

### Status

The project is at a very early stage and it is unclear how far I
will push it. Feel free to try it out. Feedback and contributions
are welcome. But please to not expect thing to work without any
problems.

### Usage Example

```
$ ./Grainfather.py -h
Usage: ./Grainfather.py [options]
  -v           --verbose             increase the logging level
  -d           --debug               set to maximum logging level
  -h           --help                this help message
  -u username  --user username       Grainfather community username
  -p password  --password password   Grainfather community password
  -P file      --pwfile file         read password from file
  -k file      --kbhfile file        Kleiner Brauhelfer database file

$ ./Grainfather.py -v -u f-grainfather@familie-steinberg.org -P ~/.grainfather.passwd -k ~/.kleiner-brauhelfer/kb_daten.sqlite push "#004 Altbier"
INFO:session:GET https://oauth.grainfather.com/customer/account/login/ -> 200
INFO:session:POST https://oauth.grainfather.com/customer/account/loginPost/ -> 200
INFO:session:GET https://brew.grainfather.com -> 200
INFO:session:GET https://brew.grainfather.com/my-recipes/data?page=1 -> 200
INFO:session:GET https://brew.grainfather.com/my-recipes/data?page=2 -> 200
INFO:interpreter:Updating <bound Recipe id 181607 named "#004 Altbier">
INFO:session:PUT https://brew.grainfather.com/recipes/181607 -> 200
INFO:session:GET https://brew.grainfather.com/logout -> 200
```

### TODO

- implement recipe["fermentation_steps"]
- more operations: delete (rename? ...others?)
- better error handling
- document KBH [[]]-tags
- implement more KBH [[]]-tags (e.g. malt-ppg)
- split: Python API / command line tool
- write first line of KBH comment to GF description
- allow a separator to suppress parts of KBH comments
- push: compare mtime, push only updated recipes
- ...then we should also implement a --force option

Late future:

- ratings
- (partial) sync back from GF to KBH?


[1]: https://grainfather.com
[2]: https://brew.grainfather.com
[3]: https://github.com/Gremmel/kleiner-brauhelfer
[4]: LICENSE.txt



