#
# Copyright (C) 2007 by Johan De Taeye
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser
# General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA
#

#  file     : $URL$
#  revision : $LastChangedRevision$  $LastChangedBy$
#  date     : $LastChangedDate$

import random
from optparse import make_option
from datetime import timedelta, datetime, date

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.conf import settings
from django.utils.translation import ugettext as _
from django.contrib.auth.models import User

from input.models import *
from execute.models import log


class Command(BaseCommand):

  help = '''
      This script is a simple, generic model generator.
      This test script is meant more as a sample for your own tests on
      evaluating performance, memory size, database size, ...

      The autogenerated supply network looks schematically as follows:
        [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
        [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
        [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
        [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
        [ Operation -> buffer ] ...   [ -> Operation -> buffer ]  [ Delivery ]
            ...                                  ...
      Each row represents a cluster.
      The operation+buffer are repeated as many times as the depth of the supply
      path parameter.
      In each cluster a single item is defined, and a parametrizable number of
      demands is placed on the cluster.
    '''

  option_list = BaseCommand.option_list + (
      make_option('--verbosity', dest='verbosity', type='choice',
        choices=['0', '1', '2'],
        help='Verbosity level; 0=minimal output, 1=normal output, 2=all output'),
      make_option('--user', dest='user', type='string',
        help='User running the command'),
      make_option('--cluster', dest='cluster', type="int",
        help='Number of end items'),
      make_option('--demand', dest='demand', type="int",
        help='Demands per end item'),
      make_option('--forecast_per_item', dest='forecast_per_item', type="int",
        help='Monthly forecast per end item'),
      make_option('--level', dest='level', type="int",
        help='Depth of bill-of-material'),
      make_option('--resource', dest='resource', type="int",
        help='Number of resources'),
      make_option('--resource_size', dest='resource_size', type="int",
        help='Size of each resource'),
      make_option('--components', dest='components', type="int",
        help='Total number of components'),
      make_option('--components_per', dest='components_per', type="int",
        help='Number of components per end item'),
      make_option('--deliver_lt', dest='deliver_lt', type="int",
        help='Average delivery lead time of orders'),
      make_option('--procure_lt', dest='procure_lt', type="int",
        help='Average procurement lead time'),
      make_option('--currentdate', dest='currentdate', type="string",
        help='Current date of the plan in YYYY-MM-DD format')
  )

  requires_model_validation = False

  def get_version(self):
    return settings.FREPPLE_VERSION


  @transaction.commit_manually
  def handle(self, **options):
    # Make sure the debug flag is not set!
    # When it is set, the django database wrapper collects a list of all sql
    # statements executed and their timings. This consumes plenty of memory
    # and cpu time.
    tmp_debug = settings.DEBUG
    settings.DEBUG = False

    # Pick up the options
    if 'verbosity' in options: verbosity = int(options['verbosity'] or '1')
    else: verbosity = 1
    if 'user' in options: user = options['user']
    else: user = ''
    if 'cluster' in options: cluster = int(options['cluster'] or '100')
    else: cluster = 100
    if 'demand' in options: demand = int(options['demand'] or '30')
    else: demand = 30
    if 'forecast_per_item' in options: forecast_per_item = int(options['forecast_per_item'] or '50')
    else: forecast_per_item = 50
    if 'level' in options: level = int(options['level'] or '5')
    else: level = 5
    if 'resource' in options: resource = int(options['resource'] or '50')
    else: resource = 50
    if 'resource_size' in options: resource_size = int(options['resource_size'] or '4')
    else: resource_size = 4
    if 'components' in options: components = int(options['components'] or '200')
    else: components = 200
    if 'components_per' in options: components_per = int(options['components_per'] or '5')
    else: components_per = 5
    if 'deliver_lt' in options: deliver_lt = int(options['deliver_lt'] or '30')
    else: deliver_lt = 30
    if 'procure_lt' in options: procure_lt = int(options['procure_lt'] or '40')
    else: procure_lt = 40
    if 'currentdate' in options: currentdate = options['currentdate'] or '2007-01-01'
    else: currentdate = '2007-01-01'

    random.seed(100) # Initialize random seed to get reproducible results
    cnt = 100000     # A counter for operationplan identifiers

    # Pick up the startdate
    try:
      startdate = datetime.strptime(currentdate,'%Y-%m-%d')
    except Exception, e:
      raise CommandError("current date is not matching format YYYY-MM-DD")

    # Check whether the database is empty
    if Buffer.objects.count()>0 or Item.objects.count()>0:
      raise CommandError("Database must be empty before creating a model")

    try:
      # Logging the action
      log(
        category='CREATE', user=user,
        message = u'%s : %d %d %d %d %d %d %d %d %d %d'
          % (_('Start creating sample model with parameters'),
             cluster, demand, forecast_per_item, level, resource,
             resource_size, components, components_per, deliver_lt,
             procure_lt)
        ).save()

      # Performance improvement for sqlite during the bulky creation transactions
      if settings.DATABASE_ENGINE == 'sqlite3':
        connection.cursor().execute('PRAGMA synchronous=OFF')

      # Plan start date
      if verbosity>0: print "Updating plan..."
      try:
        p = Plan.objects.all()[0]
        p.currentdate = startdate
        p.save()
      except:
        # No plan exists yet
        p = Plan(name="frePPLe", currentdate=startdate)
        p.save()

      # Update the user horizon
      try:
        userprofile = User.objects.get(username=user).get_profile()
        userprofile.startdate = startdate.date()
        userprofile.enddate = (startdate + timedelta(365)).date()
        userprofile.save()
      except:
        pass # It's not important if this fails

      # Planning horizon
      # minimum 10 daily buckets, weekly buckets till 40 days after current
      if verbosity>0: print "Updating horizon telescope..."
      updateTelescope(10, 40)

      # Working days calendar
      if verbosity>0: print "Creating working days..."
      workingdays = Calendar(name="Working Days")
      workingdays.save()
      cur = None
      for i in Dates.objects.all():
        curdate = datetime(i.day.year, i.day.month, i.day.day)
        dayofweek = int(curdate.strftime("%w")) # day of the week, 0 = sunday, 1 = monday, ...
        if dayofweek == 1:
          # A bucket for the working week: monday through friday
          if cur:
            cur.enddate = curdate
            cur.save()
          cur = Bucket(startdate=curdate, value=1, calendar=workingdays)
        elif dayofweek == 6:
          # A bucket for the weekend
          if cur:
            cur.enddate = curdate
            cur.save()
          cur = Bucket(startdate=curdate, value=0, calendar=workingdays)
      if cur: cur.save()
      transaction.commit()

      # Create a random list of categories to choose from
      categories = [ 'cat A','cat B','cat C','cat D','cat E','cat F','cat G' ]

      # Create customers
      if verbosity>0: print "Creating customers..."
      cust = []
      for i in range(100):
        c = Customer(name = 'Cust %03d' % i)
        cust.append(c)
        c.save()
      transaction.commit()

      # Create resources and their calendars
      if verbosity>0: print "Creating resources and calendars..."
      res = []
      for i in range(resource):
        loc = Location(name='Loc %05d' % int(random.uniform(1,cluster)))
        loc.save()
        cal = Calendar(name='capacity for res %03d' %i, category='capacity')
        bkt = Bucket(startdate=startdate, value=resource_size, calendar=cal)
        cal.save()
        bkt.save()
        r = Resource(name = 'Res %03d' % i, maximum=cal, location=loc)
        res.append(r)
        r.save()
      transaction.commit()

      # Create the components
      if verbosity>0: print "Creating raw materials..."
      comps = []
      comploc = Location(name='Procured materials')
      comploc.save()
      for i in range(components):
        it = Item(name = 'Component %04d' % i, category='Procured')
        it.save()
        ld = abs(round(random.normalvariate(procure_lt,procure_lt/3)))
        c = Buffer(name = 'Component %04d' % i,
             location = comploc,
             category = 'Procured',
             item = it,
             type = 'buffer_procure',
             min_inventory = 20,
             max_inventory = 100,
             size_multiple = 10,
             leadtime = ld * 86400,
             onhand = round(forecast_per_item * random.uniform(1,3) * ld / 30),
             )
        comps.append(c)
        c.save()
      transaction.commit()

      # Loop over all clusters
      durations = [ 86400, 86400*2, 86400*3, 86400*5, 86400*6 ]
      for i in range(cluster):
        if verbosity>0: print "Creating cluster %d..." % i

        # location
        loc = Location(name='Loc %05d' % i)
        loc.save()

        # Item and delivery operation
        oper = Operation(name='Del %05d' % i, sizemultiple=1)
        oper.save()
        it = Item(name='Itm %05d' % i, operation=oper, category=random.choice(categories))
        it.save()

        # Forecast
        fcst = Forecast( \
          name='Forecast item %05d' % i,
          calendar=workingdays,
          item=it,
          maxlateness=60*86400, # Forecast can only be planned 2 months late
          priority=3, # Low priority: prefer planning orders over forecast
          )
        fcst.save()

        # This method will take care of distributing a forecast quantity over the entire
        # horizon, respecting the bucket weights.
        fcst.setTotal(startdate, startdate + timedelta(365), forecast_per_item * 12)

        # Level 0 buffer
        buf = Buffer(name='Buf %05d L00' % i,
          item=it,
          location=loc,
          category='00'
          )
        fl = Flow(operation=oper, thebuffer=buf, quantity=-1)
        fl.save()

        # Demand
        for j in range(demand):
          dm = Demand(name='Dmd %05d %05d' % (i,j),
            item=it,
            quantity=int(random.uniform(1,6)),
            # Exponential distribution of due dates, with an average of deliver_lt days.
            due = startdate + timedelta(days=round(random.expovariate(float(1)/deliver_lt/24))/24),
            # Orders have higher priority than forecast
            priority=random.choice([1,2]),
            customer=random.choice(cust),
            category=random.choice(categories)
            )
          dm.save()

        # Create upstream operations and buffers
        ops = []
        for k in range(level):
          if k == 1 and res:
            # Create a resource load for operations on level 1
            oper = Operation(name='Oper %05d L%02d' % (i,k),
              type='operation_time_per',
              duration_per=86400,
              sizemultiple=1,
              )
            oper.save()
            Load(resource=random.choice(res), operation=oper).save()
          else:
            oper = Operation(name='Oper %05d L%02d' % (i,k),
              duration=random.choice(durations),
              sizemultiple=1,
              )
            oper.save()
          ops.append(oper)
          buf.producing = oper
          # Some inventory in random buffers
          if random.uniform(0,1) > 0.8: buf.onhand=int(random.uniform(5,20))
          buf.save()
          Flow(operation=oper, thebuffer=buf, quantity=1, type="flow_end").save()
          if k != level-1:
            # Consume from the next level in the bill of material
            buf = Buffer(name='Buf %05d L%02d' % (i,k+1),
              item=it,
              location=loc,
              category='%02d' % (k+1)
              )
            buf.save()
            Flow(operation=oper, thebuffer=buf, quantity=-1).save()

        # Consume raw materials / components
        c = []
        for j in range(components_per):
          o = operation = random.choice(ops)
          b = random.choice(comps)
          while (o,b) in c:
            # A flow with the same operation and buffer already exists
            o = operation = random.choice(ops)
            b = random.choice(comps)
          c.append( (o,b) )
          fl = Flow(operation = o, thebuffer = b, quantity = random.choice([-1,-1,-1,-2,-3])).save()

        # Commit the current cluster
        transaction.commit()

      # Log success
      log(category='CREATE', user=user,
        message=_('Finished creating sample model')).save()

    except Exception, e:
      # Log failure and rethrow exception
      try: log(category='CREATE', user=user,
        message=u'%s: %s' % (_('Failure creating sample model'),e)).save()
      except: pass
      raise CommandError(e)

    finally:
      # Commit it all, even in case of exceptions
      transaction.commit()
      settings.DEBUG = tmp_debug


@transaction.commit_manually
def updateTelescope(min_day_horizon=10, min_week_horizon=40):
  '''
  Update for the telescopic horizon.
  The first argument specifies the minimum number of daily buckets. Additional
  daily buckets will be appended till we come to a monday. At that date weekly
  buckets are starting.
  The second argument specifies the minimum horizon with weeks before the
  monthly buckets. The last weekly bucket can be a partial one: starting on
  monday and ending on the first day of the next calendar month.
  '''

  # Make sure the debug flag is not set!
  # When it is set, the django database wrapper collects a list of all sql
  # statements executed and their timings. This consumes plenty of memory
  # and cpu time.
  tmp_debug = settings.DEBUG
  settings.DEBUG = False

  # Performance improvement for sqlite during the bulky creation transactions
  if settings.DATABASE_ENGINE == 'sqlite3':
    connection.cursor().execute('PRAGMA synchronous=OFF')
  first_date = Dates.objects.all()[0].day
  current_date = Plan.objects.all()[0].currentdate
  limit = (current_date + timedelta(min_day_horizon)).date()
  mode = 'day'
  try:
    for i in Dates.objects.all():
      if i.day < current_date.date():
        # A single bucket for all dates in the past
        i.default = 'past'
        i.default_start = first_date
        i.default_end = current_date.date()
      elif mode == 'day':
        # Daily buckets
        i.default = str(i.day)[2:]  # Leave away the leading century, ie "20"
        i.default_start = i.day_start
        i.default_end = i.day_end
        if i.day >= limit and i.dayofweek == 0:
          mode = 'week'
          limit = (current_date + timedelta(min_week_horizon)).date()
          limit =  date(limit.year+limit.month/12, limit.month+1-12*(limit.month/12), 1)
      elif i.day < limit:
        # Weekly buckets
        i.default = i.week
        i.default_start = i.week_start
        i.default_end = (i.week_end > limit and limit) or i.week_end
      else:
        # Monthly buckets
        i.default = i.month
        i.default_start = i.month_start
        i.default_end = i.month_end
      i.save()
  finally:
    transaction.commit()
    settings.DEBUG = tmp_debug
