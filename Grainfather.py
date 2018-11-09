#!/usr/bin/env python3
"""
grainfather - Manage Grainfather community brew recipes

Copyright (C) 2018 Frank Steinberg <frank@familie-steinberg.org>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
"""



import os
import re
import sys
import time
import json
import getopt
import fnmatch
import logging
import sqlite3
import requests
import datetime
import http.client
from enum import Enum



DEFAULT_SOURCE		= "Frank's Grainfather Community Tool"



class KleinerBrauhelfer(object):

    """Representation of a "Kleiner Brauhelfer" database."""
    
    conn = None
    logger = None



    def __init__(self, path):

        """Opens the KBH SQlite3 database given by the filesystem path parameter."""

        self.logger = logging.getLogger('kbh')

        fd = os.open(path, os.O_RDONLY)
        os.close(fd)
        self.conn = sqlite3.connect(path, uri=True)
        self.conn.row_factory = sqlite3.Row



    def extractFromText(self, text, tag, default=None):

        """Extracts a value from a given text addressed by a given tag.
        This is used to encode some special attributes in KBH comment fields
        that are not otherwise represented in the KBH database. E.g.
        the substring "[[BJCP-Style: 7B]]" in a recipe comment may be
        converted to an according Grainfather recipe attribute."""

        value = default
        
        for line in text.splitlines():
            if ("[[%s:" % (tag)) in line:
                pattern = r'^.*\[\[' + re.escape(tag) + r' *: *([^\]]*)\]\].*$'
                value = re.sub(pattern, r'\1', line, re.IGNORECASE)

        if default != None:
            if default.__class__.__name__ == "bool":
                if str(value).lower() in [ "1", "true", "y", "yes", "ja" ]:
                    value = True
                #if str(value).lower() in [ "0", "false", "n", "no", "nein" ]:
                else:
                    value = False
                    
        return value



    def localToUtc(self, t):

        u = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", 
                          time.gmtime(time.mktime(time.strptime(t, "%Y-%m-%dT%H:%M:%S"))))
        return u



    def sudToRecipe(self, sud):

        """Converts a "sud" read from the KBH database into a Recipe object.
        Subsequent readings from the database will be issued to fill the
        Recipe object with as much useful information as passible."""

        c = self.conn.cursor()

        c.execute("SELECT * FROM Hauptgaerverlauf WHERE SudID = ? ORDER BY Zeitstempel", (sud["ID"],))
        restextrakt = 0
        a = c.fetchall()
        if len(a) > 0:
            restextrakt = float(a[-1]["SW"])

        data = {}
        data["name"] = sud["Sudname"]
        if sud["erg_Alkohol"] > 0:
            data["abv"] = sud["erg_Alkohol"]
        data["batch_size"] = sud["WuerzemengeAnstellen"] # with GF batch size does not include losses
        data["boil_size"] = sud["WuerzemengeKochende"]
        data["boil_time"] = sud["KochdauerNachBitterhopfung"]
        data["og"] = Session.platoToGravity(sud["SWAnstellen"])
        data["fg"] = Session.platoToGravity(restextrakt)

        srm = round(float(sud["erg_Farbe"]) * 0.508)

        # formula from https://brauerei.mueggelland.de/vergaerungsgrad.html
        stammwuerze = float(sud["SWAnstellen"])
        wfg = 0.1808 * stammwuerze + 0.1892 * restextrakt;
        d = 261.1 / (261.53 - restextrakt);
        abw = (stammwuerze - wfg) / (2.0665 - 0.010665 * stammwuerze);
        kcal = round((6.9 * abw + 4 * ( wfg - 0.1 )) * 10 * 0.1 * d);
        # we reverse engineered this calories factor
        data["calories"] = round(kcal * 3.55)
        # dates seem to be overwritten by the GF server
        # in fact, they update timestamps seems to updates somewhat later ?!?!
        data["created_at"] = self.localToUtc(sud["Erstellt"])
        data["updated_at"] = self.localToUtc(sud["Gespeichert"])
        # pick description from first paragraph of "Kommentar"
        data["description"] = sud["Kommentar"].splitlines()[0]
        data["efficiency"] = float("%.2f" % (sud["erg_Sudhausausbeute"] / 100.0))
        data["ibu"] = sud["IBU"]
        data["is_active"] = True # what is this?
        if sud["JungbiermengeAbfuellen"] > 0 and sud["WuerzemengeVorHopfenseihen"] > 0:
            data["losses"] = float("%.1f" % (sud["WuerzemengeVorHopfenseihen"] - sud["JungbiermengeAbfuellen"]))
        data["notes"] = re.sub(r'\[\[[^\]]*\]\]\n?', r'', sud["Kommentar"])
        data["srm"] = srm
        data["bjcp_style_id"] = self.extractFromText(sud["Kommentar"], "BJCP-Style")
        data["is_public"] = self.extractFromText(sud["Kommentar"], "Public", default=False)
        data["image_url"] = self.extractFromText(sud["Kommentar"], "Image")
        # hack hack
        if data["image_url"]:
            data["image_url"] = "&src=" + data["image_url"]
        
        # fermentables
        data["fermentables"] = []
        c.execute("SELECT * FROM Malzschuettung WHERE SudID = ? ORDER BY Prozent DESC", (sud["ID"],))
        malze = c.fetchall()
        for malz in malze:
            data["fermentables"].append({
                    "name": malz["Name"],
                    "ppg": 35.0, # a rough estimate
                    "lovibond": Session.ebcToLovibond(float(malz["Farbe"])),
                    "fermentable_usage_type_id": FermantableUsageType.MASH.value, # kbh supports just mash for "Malz"
                    "fermentable_id": None,
                    "amount": float("%.3f" % (malz["erg_Menge"])) })
        # we assume "Weitere Zutaten" with "Ausbeute > 0" are other fermentables
        c.execute("SELECT * FROM WeitereZutatenGaben WHERE SudID = ? AND Typ != 100 AND Ausbeute > 0 ORDER BY erg_Menge DESC", (sud["ID"],))
        zutaten = c.fetchall()
        for zutat in zutaten:
            if zutat["Zeitpunkt"] == 2:
                usage = FermantableUsageType.MASH.value
            elif zutat["Zeitpunkt"] == 1:
                usage = FermantableUsageType.EXTRACT.value
            elif zutat["Zeitpunkt"] == 0:
                usage = FermantableUsageType.LATEADDITION.value
            data["fermentables"].append({
                    "name": zutat["Name"],
                    "ppg": round(float(zutat["Ausbeute"]) / 2.5),
                    "lovibond": Session.ebcToLovibond(float(zutat["Farbe"])),
                    "fermentable_usage_type_id": usage,
                    "fermentable_id": None,
                    "amount": float("%.3f" % (zutat["erg_Menge"] / 1000)) })

        # adjuncts
        data["adjuncts"] = []
        c.execute("SELECT * FROM WeitereZutatenGaben WHERE SudID = ? AND Typ != 100 AND Ausbeute <= 0 ORDER BY erg_Menge DESC", (sud["ID"],))
        zutaten = c.fetchall()
        for zutat in zutaten:
            if zutat["Zeitpunkt"] == 2:
                usage = AdjunctUsageType.MASH.value
            elif zutat["Zeitpunkt"] == 1:
                if zutat["Zugabedauer"] == 0:
                    usage = AdjunctUsageType.FLAMEOUT.value
                else:
                    usage = AdjunctUsageType.BOIL.value
            elif zutat["Zeitpunkt"] == 0:
                usage = AdjunctUsageType.PRIMARY.value
            data["adjuncts"].append({
                    "name": zutat["Name"],
                    "adjunct_usage_type_id": usage,
                    "unit": "g",
                    "amount": float("%.3f" % (zutat["erg_Menge"])) })
            if zutat["Zugabedauer"] > 0:
                t = zutat["Zugabedauer"]
                if t >= 1440:
                    t = round(t / 1440)
                data["adjuncts"][-1]["time"] = t

        # hops
        data["hops"] = []
        c.execute("SELECT * FROM HopfenGaben WHERE SudID = ? AND Vorderwuerze = 1 ORDER BY erg_Menge DESC", (sud["ID"],))
        diehopfen = c.fetchall()
        for hopfen in diehopfen:
            if hopfen["Pellets"] == 1:
                typeid = HopType.PELLET.value
            else:
                typeid = HopType.PLUG.value # kbh does not differ leaf and plug
            data["hops"].append({
                    "name": hopfen["Name"],
                    "aa": hopfen["Alpha"],
                    "hop_type_id": typeid,
                    "hop_usage_type_id": HopUsageType.FIRSTWORT.value,
                    "time": data["boil_time"],
                    "amount": float("%.3f" % (hopfen["erg_Menge"])) })
        c.execute("SELECT * FROM HopfenGaben WHERE SudID = ? AND Vorderwuerze = 0 ORDER BY Zeit DESC", (sud["ID"],))
        diehopfen = c.fetchall()
        for hopfen in diehopfen:
            if hopfen["Pellets"] == 1:
                typeid = HopType.PELLET.value
            else:
                typeid = HopType.PLUG.value # kbh does not differ leaf and plug
            if hopfen["Zeit"] == 0:
                usage = HopUsageType.HOPSTAND.value
                time = 0
            elif hopfen["Zeit"] < 0:
                usage = HopUsageType.HOPSTAND.value
                time = 0
            else:
                usage = HopUsageType.BOIL.value
                time = hopfen["Zeit"]
            data["hops"].append({
                    "name": hopfen["Name"],
                    "aa": hopfen["Alpha"],
                    "time": time,
                    "hop_type_id": typeid,
                    "hop_usage_type_id": usage,
                    "amount": float("%.3f" % (hopfen["erg_Menge"])) })
        c.execute("SELECT * FROM WeitereZutatenGaben WHERE SudID = ? AND Typ = 100 AND Zeitpunkt = 0 ORDER BY erg_Menge DESC", (sud["ID"],))
        zutaten = c.fetchall()
        for zutat in zutaten:
            c.execute("SELECT * FROM Hopfen WHERE Beschreibung = ?", (zutat["Name"],))
            hopfen = c.fetchone()
            if hopfen:
                aa = hopfen["Alpha"]
                if hopfen["Pellets"] == 1:
                    typeid = HopType.PELLET.value
                else:
                    typeid = HopType.PLUG.value # kbh does not differ leaf and plug
            else:
                aa = 0
                typeid = 20
            data["hops"].append({
                    "name": zutat["Name"],
                    "hop_usage_type_id": HopUsageType.DRYHOP.value,
                    "aa": aa,
                    "hop_type_id": typeid,
                    "unit": "g",
                    "amount": float("%.3f" % (zutat["erg_Menge"])) })
            if zutat["Zugabedauer"] > 0:
                t = zutat["Zugabedauer"]
                if t >= 1440:
                    t = round(t / 1440)
                data["hops"][-1]["time"] = t
            else:
                data["hops"][-1]["time"] = 0

        # mash steps
        data["mash_steps"] = []
        i = 0
        c.execute("SELECT * FROM Rasten WHERE SudID = ?", (sud["ID"],))
        rasten = c.fetchall()
        for rast in rasten:
            data["mash_steps"].append({
                    "order": i,
                    "name": rast["RastName"],
                    "temperature": rast["RastTemp"],
                    "time": rast["RastDauer"] })
            i += 1

        # kbh supports only one yeast in a recipe
        if sud["HefeAnzahlEinheiten"] == 0:
            data["yeasts"] = []
        else:
            data["yeasts"] = [ { "name": sud["AuswahlHefe"], "amount": sud["HefeAnzahlEinheiten"], "unit": "packets" } ]
            c.execute("SELECT * FROM Hefe WHERE Beschreibung = ?", (sud["AuswahlHefe"],))
            hefe = c.fetchone()
            if hefe:
                data["yeasts"][0]["attenuation"] = int(re.sub(r'^([0-9]+).*$', r'\1', hefe["EVG"])) / 100
                if hefe["TypTrFl"] == 1:
                    data["yeasts"][0]["unit"] = "packets"
                else:
                    data["yeasts"][0]["unit"] = "vials"
                try:
                    amount = float(re.sub(r'^([0-9\.,]*).*$', r'\1', hefe["Verpackungsmenge"]).replace(",","."))
                    unit = re.sub(r'^[0-9\., ]*(.*)$', r'\1', hefe["Verpackungsmenge"])
                    if (amount > 0) and (unit in YeastUnitTypes):
                        data["yeasts"][0]["amount"] = amount * data["yeasts"][0]["amount"]
                        data["yeasts"][0]["unit"] = unit
                except:
                    self.logger.debug("could not convert Hefe Verpackungsmenge \"%s\" to amount and unit" % (hefe["Verpackungsmenge"]))
                
        data["bggu"] = float(data["ibu"]) / (float(data["og"]) - 1.0) / 1000

        return Recipe(data=data)


        
    def getRecipes(self, namepattern="*"):

        """Retrieves a array of Recipe objects from the KBH database based on
        an optional SQL name pattern (use e.g. % as a wildcard)."""

        c = self.conn.cursor()
        c.execute("SELECT * FROM Sud WHERE Sudname LIKE ?", (namepattern,))
        sude = c.fetchall()

        recipes = []
        for sud in sude:
            recipe = self.sudToRecipe(sud)
            recipes.append(recipe)

        return recipes



    def getRecipe(self, namepattern):

        """Retrieves one Recipe objects from the KBH database based on
        an SQL name pattern (use e.g. % as a wildcard)."""

        recipes = self.getRecipes(namepattern)

        if len(recipes) == 0:
            self.logger.warn("pattern did not result in any entry")
            return None

        if len(recipes) > 1:
            self.logger.warn("pattern did not result in a unique entry")
            return None

        return recipes[0]



class SessionError(Exception):

    """Raised when a Grainfather session error occurs."""



class Session(object):

    """Representation of a user session on the Grainfather brew community database."""
    
    session = None
    username = None
    metadata = None
    logger = None
    readonly = False



    def platoToGravity(plato):

        #gravity = 1.0 + (4.0 * float(plato) / 1000.0)

        # formula learned from https://www.brewersfriend.com/plato-to-sg-conversion-chart/
        gravity = 1.0 + ( plato / ( 258.6 - ( ( plato / 258.2 ) * 227.1 ) ) )

        gravity = "%.3f" % (gravity)

        return float(gravity)



    def ebcToLovibond(ebc):

        #lovibond = "%.3f" % ((ebc + 1.2) / 2.0)
        #lovibond = "%.3f" % (ebc / 1.97)
        #lovibond = "%.3f" % ((ebc + 1.2) / 2.6) # XXX: not yet correct

        # from GF js: function lovi2ebc(value, dec) { return ((value * 1.3546 - 0.76) * 1.97).toFixed(dec || 0); }
        # so, in reverse:
        lovibond = "%.3f" % (((ebc / 1.97) + 0.76) / 1.3546)

        return float(lovibond)



    def get(self, url):

        response = self.session.get(url)
        self.logger.info("GET %s -> %s" % (url, response.status_code))
        return response



    def post(self, url, data=None, json=None, files=None, force=False):

        if (self.readonly == False) or force:
            response = self.session.post(url, data=data, json=json, files=files)
            self.logger.info("POST %s -> %s" % (url, response.status_code))
        else:
            self.logger.info("POST %s (dryrun)" % (url))
            response = None
        return response



    def put(self, url, data=None, json=None, force=False):

        if (self.readonly == False) or force:
            response = self.session.put(url, data=data, json=json)
            self.logger.info("PUT %s -> %s" % (url, response.status_code))
        else:
            self.logger.info("PUT %s (dryrun)" % (url))
            response = None
        return response



    def delete(self, url, force=False):

        if (self.readonly == False) or force:
            response = self.session.delete(url)
            self.logger.info("DELETE %s -> %s" % (url, response.status_code))
        else:
            self.logger.info("DELETE %s (dryrun)" % (url))
            response = None
        return response



    def __init__(self, username=None, password=None, readonly=False, force=False):

        self.session = requests.session()
        self.username = username
        self.readonly = readonly
        self.force = force

        self.logger = logging.getLogger('session')

        # fetch the login page
        response = self.get("https://oauth.grainfather.com/customer/account/login/")

        # pick the form_key from the login form
        form_key = None
        for line in response.text.splitlines():
            if "form_key" in line:
                form_key = re.sub(r'^.*value="([a-zA-Z_0-9]*).*$', r'\1', line)
        if (not form_key):
            self.logger.error("Could not fetch form_key from login page")

        # post to the login form
        payload = {'form_key': form_key, 'login[username]': username, 'login[password]': password}
        response = self.post("https://oauth.grainfather.com/customer/account/loginPost/", data=payload, force=True)

        # fetch start page from the recipe creator
        response = self.get("https://brew.grainfather.com")

        # pick session metadata from response and set the CSRF token for this session
        self.metadata = None
        for line in response.text.splitlines():
            if "window.Grainfather" in line:
                s = re.sub(r'window.Grainfather *= *', r'', line)
                self.metadata = json.loads(s)
        if (not self.metadata):
            self.logger.error("Could not fetch session data from login response")
        else:
            self.session.headers.update({'X-CSRF-TOKEN': self.metadata["csrfToken"]})



    def logout(self):

        response = self.get("https://brew.grainfather.com/logout")



    def register(self, obj, id=None):

        """If the given object has been defined locally and is not yet bound to
        a Grainfather session, this method will bind it without actually saving
        it to the Grainfather site. Saving can be done by a subsequent save() call
        on the object."""

        if id:
            obj.set("id", id)

        if obj.session == None:
            obj.session = self
        else:
            self.logger.error("%s is already bound to a session" % obj)



    def __str__(self):

        return "<Session of user %s>" % (self.username)



    def getRecipe(self, id):

        return Recipe(self, id=id)



    def getMyRecipes(self, namepattern=None, full=False):

        recipes = []

        url = "https://brew.grainfather.com/my-recipes/data?page=1"

        while url:

            response = self.get(url)
            responsedata = json.loads(response.text)

            for data in responsedata["data"]:
                if full:
                    recipes.append(self.getRecipe(id=data["id"]))
                else:
                    recipe = Recipe(data=data)
                    recipe.session = self
                    recipes.append(recipe)
                    
            if "next_page_url" in responsedata:
                url = responsedata["next_page_url"]
            else:
                break

        if namepattern:
            recipes = list(filter(lambda r: fnmatch.fnmatch(r.get("name"), namepattern), recipes))

        return recipes



class AdjunctUsageType(Enum):

    MASH		= 10	# min
    SPARGE		= 15	# min
    BOIL		= 20	# min
    FLAMEOUT		= 25	# min
    PRIMARY		= 30	# days
    SECONDARY		= 40	# days
    BOTTLE		= 50	# min



class FermantableUsageType(Enum):

    MASH		= 10
    EXTRACT		= 20	# does this mean during boil or does this mean the malt is given as (dry or liquid) extract?
    STEEP		= 30	# what is this? i guess it means during the last few minutes of the boil
    LATEADDITION	= 40	# what is this? probably after boil during fermentation or even later?



class HopType(Enum):

    LEAF		= 10
    PELLET		= 20
    PLUG		= 30



class HopUsageType(Enum):

    MASH		= 10	# min
    FIRSTWORT		= 15	# min
    BOIL		= 20	# min
    HOPSTAND		= 30	# min
    DRYHOP		= 40	# days



class RecipeType(Enum):

    ALLGRAIN		= 10
    # TBD: others?



class UnitType(Enum):

    METRIC		= 10
    # TBD: others?



YeastUnitTypes = [ "packets", "vials", "g", "ml" ]



AdjunctUnitTypes = [ "each", "kg", "g", "l", "ml", "tbsp", "tsp" ]



class Object(object):

    session = None
    data = None



    def __init__(self, session=None, id=None, data=None):

        self.session = session
        self.data  = data

        if self.session:
            
            if id:

                self.reload(id=id)

            elif data:
                
                self.save()



    def tidy(self):

        return



    def reload(self, id=None):

        if not id:
            id = self.data["id"]

        response = self.session.get(self.urlload.format(api_token=self.session.metadata["user"]["api_token"], id=id))
        self.data = json.loads(response.text)



    def save(self, id=None):

        if id:
            self.data["id"] = id

        self.tidy()

        if "id" in self.data:
            response = self.session.put(self.urlsave.format(api_token=self.session.metadata["user"]["api_token"], id=self.data["id"]), json=self.data)
        else:
            response = self.session.post(self.urlcreate.format(api_token=self.session.metadata["user"]["api_token"]), json=self.data)

        if response:
            self.data = json.loads(response.text)



    def delete(self):

        response = self.session.delete(self.urlsave.format(api_token=self.session.metadata["user"]["api_token"], id=self.data["id"]))



    def __str__(self):

        s = "<"
        if "status" in self.data:
            s += "%s " % self.data["status"]
        else:
            if self.session:
                s += "bound "
            else:
                s += "unbound "
        s += "%s" % (self.__class__.__name__)
        if "id" in self.data:
            s += " id %s" % self.data["id"]
        if "name" in self.data:
            s += " named \"%s\"" % self.data["name"]
        s += ">"

        return s



    def __repr__(self):

        return self.__str__()



    def set(self, attr, value):

        self.data[attr] = value



    def get(self, attr):

        return self.data[attr]



    def print(self):

        print(json.dumps(self.data, sort_keys=True, indent=4))



class Recipe(Object):

    urlload = "https://brew.grainfather.com/recipes/data/{id}"
    urlsave = "https://brew.grainfather.com/recipes/{id}"
    urlcreate = "https://brew.grainfather.com/recipes"



    def __init__(self, session=None, id=None, xmlfilename=None, data=None):

        if session and xmlfilename:

            # post xml to convert to json
            self.session.logger.info("Converting XML recipe file to JSON")
            response = self.session.post("https://brew.grainfather.com/recipes/xml", files={'xml': (filename, open(filename, 'rb'), 'text/xml')})
            data = json.loads(response.text)

        super(Recipe, self).__init__(session=session, id=id, data=data)

     


    def tidy(self):

        # add required fields, if missing
        if not 'unit_type_id' in self.data:
            self.data['unit_type_id'] = UnitType.METRIC.value;
        if not 'recipe_type_id' in self.data:
            self.data['recipe_type_id'] = RecipeType.ALLGRAIN.value;

        # others
        if not 'source' in self.data:
            self.data['source'] = DEFAULT_SOURCE
        if not 'parent_recipe_id' in self.data:
            self.data['parent_recipe_id'] = None



class Fermentable(Object):

    # TBD... how can we access specific ingredients?

    #urlload = "https://brew.grainfather.com/api/ingredients/fermentables?api_token={api_token}&id={id}"
    #urlload = "https://brew.grainfather.com/api/ingredients/fermentables/{id}?api_token={api_token}"
    urlload = "https://brew.grainfather.com/api/ingredients/fermentables?api_token={api_token}&q={id}"
    urlsave = None # XXX yet
    urlcreate = None # XXX yet



class Interpreter(object):

    kbh = None
    session = None
    logger = None


    def __init__(self, kbh=None, session=None):

        self.kbh = kbh
        self.session = session

        self.logger = logging.getLogger('interpreter')



    def list(self, namepattern=None):

        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        recipes = self.session.getMyRecipes(namepattern)

        for recipe in recipes:
            
            print(recipe)



    def dump(self, namepattern=None):

        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        recipes = self.session.getMyRecipes(namepattern)

        for recipe in recipes:
            
            recipe.print()



    def delete(self, namepattern=None):
        
        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        if not namepattern:
            self.logger.error("No name pattern supplied")
            return

        recipes = self.session.getMyRecipes(namepattern)

        for recipe in recipes:
            
            recipe.delete()
            


    def push(self, namepattern=None):
        
        if not self.kbh:
            self.logger.error("No KBH database, use -k option")
            return
            
        if not self.session:
            self.logger.error("No Grainfather session, use -u and -p/-P options")
            return

        if not namepattern:
            namepattern = "*"

        recipes = self.kbh.getRecipes(namepattern.replace("*", "%"))
        if len(recipes) == 0:
            return

        # we have to know all our recipes on the GF server so that
        # we can decide which recipe to create and which to update
        gf_recipes = self.session.getMyRecipes()

        for recipe in recipes:
            
            # try to find matching GF recipe
            id = None
            for gf_recipe in gf_recipes:
                #print("XXX %s %s" % (gf_recipe.get("name"), gf_recipe.get("updated_at")))
                if gf_recipe.get("name") == recipe.get("name"):
                    id = gf_recipe.get("id")
                    break
            if id:
                if (gf_recipe.get("updated_at") > recipe.get("updated_at")) and (not self.session.force):
                    self.logger.info("%s needs no update" % gf_recipe)
                    self.logger.debug("kbh:%s, gf:%s" % (recipe.get("updated_at"), gf_recipe.get("updated_at")))
                else:
                    self.session.register(recipe, id=id)
                    self.logger.info("Updating %s" % gf_recipe)
                    self.logger.debug("kbh:%s, gf:%s" % (recipe.get("updated_at"), gf_recipe.get("updated_at")))
                    recipe.save()
            else:
                self.logger.info("Creating %s" % recipe)
                self.session.register(recipe)
                recipe.save()
            


    def pull(namepattern):

        return



def usage():
    print("""Usage: %s [options] [command [argument] ]
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
  delete "namepattern"               delete user's recipes""" % sys.argv[0])


def main():

    username = None
    password = None
    level = None
    session = None
    kbh = None
    kbhFile = None
    dryrun = False
    force = False

    logging.basicConfig()
    level = logging.WARNING
    logger = logging.getLogger()
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.WARN)

    try:
        opts, args = getopt.getopt(sys.argv[1:],
                                   "vdnfhu:p:P:k:",
                                   ["verbose", "debug", "dryrun", "force", "help", "user=", "password=", "pwfile=", "kbhfile="])
    except getopt.GetoptError as err:
        print(str(err))
        usage()
        sys.exit(2)

    for o, a in opts:

        if o in ("-v", "--verbose"):
            if level == logging.WARNING:
                level = logging.INFO
                logger.setLevel(level)
            elif level == logging.INFO:
                level = logging.DEBUG
                logger.setLevel(level)
            else:
                requests_log.setLevel(level)
                requests_log.propagate = True

        elif o in ("-d", "--debug"):
            level = logging.DEBUG
            logger.setLevel(level)
            requests_log.setLevel(level)
            requests_log.propagate = True
            http.client.HTTPConnection.debuglevel = 1

        elif o in ("-n", "--dryrun"):
            dryrun = True

        elif o in ("-f", "--force"):
            force = True

        elif o in ("-h", "--help"):
            usage()
            sys.exit()

        elif o in ("-u", "--user"):
            username = a

        elif o in ("-p", "--password"):
            password = a

        elif o in ("-P", "--pwfile"):
            try:
                with open(a) as f:
                    password = f.readline()
                    password = password.rstrip('\r\n')
            except Exception as error:
                logging.getLogger().error("Could not read password from file: %s" % (error))

        elif o in ("-k", "--kbhfile"):
            kbhFile = a

        else:
            assert False, "unhandled option"

    if (username and password):
        session = Session(username, password, readonly=dryrun, force=force)

    if (kbhFile):
        kbh = KleinerBrauhelfer(kbhFile)

    interpreter = Interpreter(kbh=kbh, session=session)

    op = None
    arg = None
    if len(args) >= 1:
        op = args[0]
    if len(args) >= 2:
        arg = args[1]

    result = getattr(interpreter, op)(arg)

    if session:
        session.logout()



if __name__ == '__main__':
    sys.exit(main())

