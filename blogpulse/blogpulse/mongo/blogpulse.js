// =====================================================================
// BlogPulse | MongoDB part | posts, embedded comments and tags
// Run in mongosh:   mongosh --file mongo/blogpulse.js
// (load the data first:
//   mongoimport --db blogpulse --collection posts --drop --jsonArray --file mongo/posts.json )
// author_id / user_id point to users.user_id in PostgreSQL.
// =====================================================================
const bp = db.getSiblingDB("blogpulse");
const posts = bp.posts;
print("posts loaded:", posts.countDocuments());

// ---------------------------------------------------------------------
// 1. SAMPLE DOCUMENT (what one post looks like)
// ---------------------------------------------------------------------
printjson(posts.findOne({ status: "published", "comments.0": { $exists: true } }));

// ---------------------------------------------------------------------
// 2. INDEXES  (tags, author, date, unique slug, text search)
// ---------------------------------------------------------------------
posts.createIndex({ slug: 1 },                      { unique: true, name: "ux_slug" });
posts.createIndex({ tags: 1 },                      { name: "ix_tags" });            // multikey (array)
posts.createIndex({ author_id: 1, created_at: -1 }, { name: "ix_author_date" });     // compound
posts.createIndex({ created_at: -1 },               { name: "ix_created" });
posts.createIndex({ title: "text", body: "text" },  { name: "tx_title_body" });      // full-text
printjson(posts.getIndexes().map(i => i.name));

// ---------------------------------------------------------------------
// 3. CRUD
// ---------------------------------------------------------------------
// CREATE
const ins = posts.insertOne({
  title: "MongoDB indexing in five minutes", slug: "mongodb-indexing-in-five-minutes",
  author_id: 2, author_name: "Liam Reddy", category: "Tutorial",
  tags: ["mongodb", "indexing", "databases"],
  body: "How compound and multikey indexes speed up queries.",
  status: "published", views: 0, likes: 0, created_at: new Date(), comments: []
});
const newId = ins.insertedId;
posts.insertMany([
  { title: "Draft: window functions", slug: "draft-window-functions", author_id: 2, author_name: "Liam Reddy",
    category: "Guide", tags: ["sql"], body: "TODO", status: "draft", views: 0, likes: 0, created_at: new Date(), comments: [] },
  { title: "Draft: Flask + PyMongo", slug: "draft-flask-pymongo", author_id: 2, author_name: "Liam Reddy",
    category: "Guide", tags: ["python", "flask", "mongodb"], body: "TODO", status: "draft", views: 0, likes: 0, created_at: new Date(), comments: [] }
]);

// READ
print("--- READ: top 5 published posts tagged 'mongodb'");
posts.find({ tags: "mongodb", status: "published" }, { title: 1, views: 1, _id: 0 })
     .sort({ views: -1 }).limit(5).forEach(printjson);
print("--- READ: text search for 'indexing'");
posts.find({ $text: { $search: "indexing" } }, { title: 1, _id: 0, score: { $meta: "textScore" } })
     .sort({ score: { $meta: "textScore" } }).limit(3).forEach(printjson);
print("--- READ: posts by author 2 since 2025-01-01:",
      posts.countDocuments({ author_id: 2, created_at: { $gte: new Date("2025-01-01") } }));

// UPDATE : add an embedded comment, bump counters, publish a draft, bulk update
posts.updateOne({ _id: newId },
  { $push: { comments: { comment_id: 1, user_id: 10, user_name: "Demo Reader", text: "Very clear, thanks!", likes: 0, created_at: new Date() } },
    $inc:  { views: 1 } });
posts.updateOne({ slug: "draft-window-functions" }, { $set: { status: "published" }, $currentDate: { updated_at: true } });
posts.updateMany({ slug: /^draft-/ }, { $set: { reviewed: false } });

// DELETE
posts.deleteOne({ slug: "draft-flask-pymongo" });
posts.deleteMany({ slug: { $in: ["draft-window-functions", "mongodb-indexing-in-five-minutes"] } });

// Index proof: the winning plan for a tag query is an index scan (IXSCAN), not COLLSCAN
printjson(posts.find({ tags: "sql" }).explain("queryPlanner").queryPlanner.winningPlan);

// ---------------------------------------------------------------------
// 4. AGGREGATION PIPELINES
// ---------------------------------------------------------------------
// A1. Top 10 posts by an engagement score (views + 5*likes + 10*comments)
print("--- A1 top posts");
posts.aggregate([
  { $match: { status: "published" } },
  { $addFields: { comment_count: { $size: "$comments" } } },
  { $addFields: { engagement: { $add: ["$views", { $multiply: ["$likes", 5] }, { $multiply: ["$comment_count", 10] }] } } },
  { $sort: { engagement: -1 } },
  { $limit: 10 },
  { $project: { _id: 0, title: 1, author_name: 1, views: 1, likes: 1, comment_count: 1, engagement: 1 } }
]).forEach(printjson);

// A2. Popular tags: $unwind the tags array, count posts, average views
print("--- A2 popular tags");
posts.aggregate([
  { $match: { status: "published" } },
  { $unwind: "$tags" },
  { $group: { _id: "$tags", posts: { $sum: 1 }, avg_views: { $avg: "$views" }, total_comments: { $sum: { $size: "$comments" } } } },
  { $sort: { posts: -1, _id: 1 } },
  { $limit: 10 },
  { $project: { _id: 0, tag: "$_id", posts: 1, avg_views: { $round: ["$avg_views", 0] }, total_comments: 1 } }
]).forEach(printjson);

// A3. Comments received per author (posts, comments, comments per post)
print("--- A3 comments per author");
posts.aggregate([
  { $match: { status: "published" } },
  { $group: { _id: { id: "$author_id", name: "$author_name" },
              posts: { $sum: 1 }, comments: { $sum: { $size: "$comments" } }, views: { $sum: "$views" } } },
  { $addFields: { comments_per_post: { $round: [{ $divide: ["$comments", "$posts"] }, 2] } } },
  { $sort: { comments: -1 } },
  { $limit: 10 },
  { $project: { _id: 0, author_id: "$_id.id", author: "$_id.name", posts: 1, comments: 1, comments_per_post: 1, views: 1 } }
]).forEach(printjson);

// A4. Posts per month (time series) using $dateToString
print("--- A4 posts per month");
posts.aggregate([
  { $match: { status: "published" } },
  { $group: { _id: { $dateToString: { format: "%Y-%m", date: "$created_at" } }, posts: { $sum: 1 }, views: { $sum: "$views" } } },
  { $sort: { _id: 1 } }
]).forEach(printjson);

// A5. Most active commenters ($unwind the embedded comments)
print("--- A5 top commenters");
posts.aggregate([
  { $unwind: "$comments" },
  { $group: { _id: "$comments.user_id", name: { $first: "$comments.user_name" }, comments: { $sum: 1 } } },
  { $sort: { comments: -1 } },
  { $limit: 5 }
]).forEach(printjson);

// ---------------------------------------------------------------------
// 5. ADMINISTRATION / BACKUP (run in a normal shell, not mongosh)
//   mongodump   --db blogpulse --out backup/
//   mongorestore --db blogpulse backup/blogpulse
//   mongoexport --db blogpulse --collection posts --out backup/posts.json
// ---------------------------------------------------------------------
